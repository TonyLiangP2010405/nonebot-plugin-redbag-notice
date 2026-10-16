"""监听配置持久化：JSON 小文件读写

配置结构非常简单（监听群列表 / 提醒用户列表 / 调试开关），因此直接用一个小
JSON 文件保存，读写都在一次同步调用内完成：单线程事件循环下不会出现读到一半
的中间状态，也就不需要额外的锁。写入使用「临时文件 + 原子替换」，避免进程被
杀掉时留下损坏的文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from nonebot import get_plugin_config
from nonebot.log import logger
from pydantic import BaseModel, Field

from .config import Config

DATA_FILE_NAME = "settings.json"
"""数据文件名（存放于插件数据目录）"""


class RedbagSettings(BaseModel):
    """监听配置"""

    groups: list[int] = Field(default_factory=list)
    """需要监听的群号列表"""

    users: list[int] = Field(default_factory=list)
    """接收私聊提醒的用户 QQ 列表"""

    debug: bool = False
    """调试模式：命中红包时把原始 json 段写入日志"""

    empty_alert: bool = False
    """空消息兜底：被监听群收到无内容消息时按疑似红包提醒

    部分协议端（如 NapCat）未实现红包元素（ElementType 9 / WALLET）的解析，
    红包会上报为无内容消息；开启后这类消息按疑似红包通知。"""

    affection_top: bool = False
    """好感榜一联动：红包命中时额外私聊该群好感度榜第一的用户

    联动 nonebot-plugin-mantou-affection，每次命中现查榜一，
    不再是榜一时自然不再提醒。插件未安装时该开关不生效。"""


def _data_dir_override() -> str:
    """读取配置中的数据目录覆盖项；nonebot 未初始化时返回空串"""
    try:
        return get_plugin_config(Config).redbag_notice_data_dir.strip()
    except Exception:
        return ""


def get_data_dir() -> Path:
    """监听配置所在目录，可由配置 ``redbag_notice_data_dir`` 覆盖"""
    override = _data_dir_override()
    if override:
        return Path(override).expanduser()
    # localstore 在 import 时即要求 nonebot 已初始化，故延迟导入
    from nonebot_plugin_localstore import get_plugin_data_dir

    return Path(get_plugin_data_dir())


def get_data_file() -> Path:
    """监听配置的文件路径"""
    return get_data_dir() / DATA_FILE_NAME


def load_settings() -> RedbagSettings:
    """读取监听配置；文件不存在或损坏时返回默认配置"""
    file = get_data_file()
    if not file.exists():
        return RedbagSettings()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        return RedbagSettings.model_validate(raw)
    except Exception as error:
        logger.warning(f"红包提醒配置文件损坏，已按默认配置处理：{file}（{error!r}）")
        return RedbagSettings()


def save_settings(settings: RedbagSettings) -> None:
    """写入监听配置（先写临时文件再原子替换）"""
    file = get_data_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(f"{file.name}.tmp")
    tmp.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, file)


def get_settings() -> RedbagSettings:
    """读取监听配置（``load_settings`` 的语义化别名）"""
    return load_settings()


def add_group(group_id: int) -> bool:
    """添加监听群，返回是否发生了变更"""
    settings = load_settings()
    if group_id in settings.groups:
        return False
    settings.groups.append(group_id)
    settings.groups.sort()
    save_settings(settings)
    return True


def remove_group(group_id: int) -> bool:
    """移除监听群，返回是否发生了变更"""
    settings = load_settings()
    if group_id not in settings.groups:
        return False
    settings.groups = [group for group in settings.groups if group != group_id]
    save_settings(settings)
    return True


def add_user(user_id: int) -> bool:
    """把用户加入提醒名单，返回是否发生了变更"""
    settings = load_settings()
    if user_id in settings.users:
        return False
    settings.users.append(user_id)
    settings.users.sort()
    save_settings(settings)
    return True


def remove_user(user_id: int) -> bool:
    """把用户移出提醒名单，返回是否发生了变更"""
    settings = load_settings()
    if user_id not in settings.users:
        return False
    settings.users = [user for user in settings.users if user != user_id]
    save_settings(settings)
    return True


def set_debug(enabled: bool) -> bool:
    """设置调试模式，返回是否发生了变更"""
    settings = load_settings()
    if settings.debug == enabled:
        return False
    settings.debug = enabled
    save_settings(settings)
    return True


def set_empty_alert(enabled: bool) -> bool:
    """设置空消息兜底提醒，返回是否发生了变更"""
    settings = load_settings()
    if settings.empty_alert == enabled:
        return False
    settings.empty_alert = enabled
    save_settings(settings)
    return True


def set_affection_top(enabled: bool) -> bool:
    """设置好感榜一联动提醒，返回是否发生了变更"""
    settings = load_settings()
    if settings.affection_top == enabled:
        return False
    settings.affection_top = enabled
    save_settings(settings)
    return True


def get_groups() -> list[int]:
    """当前监听群列表"""
    return list(load_settings().groups)


def get_watchers() -> list[int]:
    """当前提醒名单（接收私聊提醒的用户）"""
    return list(load_settings().users)


def is_debug() -> bool:
    """调试模式是否开启"""
    return load_settings().debug


def is_empty_alert() -> bool:
    """空消息兜底提醒是否开启"""
    return load_settings().empty_alert


def is_affection_top() -> bool:
    """好感榜一联动提醒是否开启"""
    return load_settings().affection_top


def is_watched_group(group_id: int) -> bool:
    """群是否在监听列表中"""
    return group_id in load_settings().groups


def should_monitor(group_id: int) -> bool:
    """是否需要处理该群的消息：群在监听列表且提醒名单非空"""
    settings = load_settings()
    return group_id in settings.groups and bool(settings.users)
