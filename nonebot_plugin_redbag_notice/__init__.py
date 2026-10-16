"""QQ 红包私聊提醒插件

超级用户在私聊中添加要监听的群；被监听的群里出现红包时，私聊通知「提醒名单」
中的用户。所有命令都在私聊中使用，监听名单保存在插件数据目录的 JSON 文件里。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

from nonebot import get_driver, on_command, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")

# 导入 notify 即注册群消息监听的响应器（notify 本身不直接引用，因此忽略 F401）
from . import notify, store  # noqa: E402, F401
from .config import Config  # noqa: E402

try:
    __version__ = pkg_version("nonebot-plugin-redbag-notice")
except PackageNotFoundError:
    __version__ = "0.3.0"

__plugin_meta__ = PluginMetadata(
    name="红包提醒",
    description="QQ 红包私聊提醒：超级用户私聊配置监听群，群内出现红包时私聊通知提醒名单",
    usage=(
        "【私聊】仅超级用户：\n"
        "红包监听 —— 查看当前配置与帮助\n"
        "监听 <群号> —— 添加监听群\n"
        "取消监听 <群号> —— 移除监听群\n"
        "监听列表 —— 列出监听群\n"
        "红包调试 开/关 —— 调试模式，命中红包时把原始 json 段写进日志\n"
        "红包空提醒 开/关 —— 无内容消息（疑似红包）兜底提醒\n"
        "红包榜一提醒 开/关 —— 额外提醒该群好感度榜一（需馒头好感插件）\n"
        "【私聊】所有人：\n"
        "红包提醒 开 —— 把自己加入提醒名单\n"
        "红包提醒 关 —— 把自己移出提醒名单\n"
        "命令前缀取决于 NoneBot 的 command_start 配置。"
    ),
    type="application",
    homepage="https://github.com/TonyLiangP2010405/nonebot-plugin-redbag-notice",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

GROUP_ID_MIN_LENGTH = 5
GROUP_ID_MAX_LENGTH = 12

_ON_WORDS = {"开", "开启", "on"}
_OFF_WORDS = {"关", "关闭", "off"}


async def _is_private_chat(event: Event) -> bool:
    """所有命令都只在私聊中响应"""
    return isinstance(event, PrivateMessageEvent)


status_cmd = on_command("红包监听", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
watch_add_cmd = on_command("监听", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
watch_del_cmd = on_command("取消监听", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
watch_list_cmd = on_command("监听列表", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
alert_cmd = on_command("红包提醒", rule=_is_private_chat, priority=10, block=True)
debug_cmd = on_command("红包调试", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
empty_alert_cmd = on_command("红包空提醒", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)
affection_top_cmd = on_command("红包榜一提醒", rule=_is_private_chat, permission=SUPERUSER, priority=10, block=True)


def _command_prefix() -> str:
    """当前命令前缀（用于帮助文本，未配置前缀时为空串）"""
    starts = get_driver().config.command_start
    return min(starts) if starts else ""


def _join_ids(ids: list[int]) -> str:
    return "、".join(str(item) for item in ids) if ids else "（空）"


def status_text() -> str:
    """当前状态 + 帮助文本"""
    settings = store.get_settings()
    prefix = _command_prefix()
    return (
        "【红包提醒】当前配置\n"
        f"监听群（{len(settings.groups)} 个）：{_join_ids(settings.groups)}\n"
        f"提醒用户（{len(settings.users)} 人）：{_join_ids(settings.users)}\n"
        f"调试模式：{'开启' if settings.debug else '关闭'}\n"
        f"空消息提醒：{'开启' if settings.empty_alert else '关闭'}\n"
        f"榜一提醒：{'开启' if settings.affection_top else '关闭'}\n"
        f"数据文件：{store.get_data_file()}\n"
        "\n"
        "管理命令（仅超级用户，私聊）：\n"
        f"{prefix}监听 <群号> —— 添加监听群\n"
        f"{prefix}取消监听 <群号> —— 移除监听群\n"
        f"{prefix}监听列表 —— 列出监听群\n"
        f"{prefix}红包调试 开/关 —— 调试模式\n"
        f"{prefix}红包空提醒 开/关 —— 无内容消息（疑似红包）兜底提醒\n"
        f"{prefix}红包榜一提醒 开/关 —— 额外提醒该群好感度榜一（需馒头好感插件）\n"
        "\n"
        "提醒命令（所有人，私聊）：\n"
        f"{prefix}红包提醒 开 —— 收到红包时私聊通知我\n"
        f"{prefix}红包提醒 关 —— 不再接收红包通知\n"
        "\n"
        "监听群为空时不会监听任何群。"
    )


def parse_group_id(text: str) -> int | None:
    """解析群号，非法时返回 None"""
    text = text.strip()
    if not text.isdigit() or not GROUP_ID_MIN_LENGTH <= len(text) <= GROUP_ID_MAX_LENGTH:
        return None
    return int(text)


def parse_switch(text: str) -> bool | None:
    """解析开/关参数，无法识别时返回 None"""
    text = text.strip().lower()
    if text in _ON_WORDS:
        return True
    if text in _OFF_WORDS:
        return False
    return None


@status_cmd.handle()
async def _handle_status() -> None:
    await status_cmd.finish(status_text())


@watch_add_cmd.handle()
async def _handle_watch_add(args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    text = args.extract_plain_text().strip()
    if not text:
        await watch_add_cmd.finish(f"用法：{prefix}监听 <群号>\n例如：{prefix}监听 123456")
    group_id = parse_group_id(text)
    if group_id is None:
        await watch_add_cmd.finish(f"群号应为 {GROUP_ID_MIN_LENGTH}~{GROUP_ID_MAX_LENGTH} 位数字，请检查后重试。")
    if store.add_group(group_id):
        await watch_add_cmd.finish(f"已开始监听群 {group_id}，群内出现红包时会私聊通知提醒名单中的用户。")
    await watch_add_cmd.finish(f"群 {group_id} 已在监听列表中。")


@watch_del_cmd.handle()
async def _handle_watch_del(args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    text = args.extract_plain_text().strip()
    if not text:
        await watch_del_cmd.finish(f"用法：{prefix}取消监听 <群号>\n例如：{prefix}取消监听 123456")
    group_id = parse_group_id(text)
    if group_id is None:
        await watch_del_cmd.finish(f"群号应为 {GROUP_ID_MIN_LENGTH}~{GROUP_ID_MAX_LENGTH} 位数字，请检查后重试。")
    if store.remove_group(group_id):
        await watch_del_cmd.finish(f"已取消监听群 {group_id}。")
    await watch_del_cmd.finish(f"群 {group_id} 不在监听列表中。")


@watch_list_cmd.handle()
async def _handle_watch_list() -> None:
    groups = store.get_groups()
    if not groups:
        await watch_list_cmd.finish("当前没有监听任何群。")
    await watch_list_cmd.finish(f"共监听 {len(groups)} 个群：\n{_join_ids(groups)}")


@alert_cmd.handle()
async def _handle_alert(event: PrivateMessageEvent, args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    action = parse_switch(args.extract_plain_text())
    user_id = int(event.get_user_id())
    if action is None:
        await alert_cmd.finish(
            f"用法：{prefix}红包提醒 开 —— 收到红包时私聊通知我\n"
            f"　　　{prefix}红包提醒 关 —— 不再接收红包通知"
        )
    if action:
        added = store.add_user(user_id)
        await alert_cmd.finish("已开启红包提醒，群内出现红包时会私聊通知你。" if added else "你已经开启红包提醒了。")
    removed = store.remove_user(user_id)
    await alert_cmd.finish("已关闭红包提醒。" if removed else "你本来就没有开启红包提醒。")


@debug_cmd.handle()
async def _handle_debug(args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    action = parse_switch(args.extract_plain_text())
    if action is None:
        await debug_cmd.finish(f"用法：{prefix}红包调试 开 / {prefix}红包调试 关")
    changed = store.set_debug(action)
    if action:
        await debug_cmd.finish("调试模式已开启：命中红包时会把原始 json 段写入日志。" if changed else "调试模式本来就是开启的。")
    await debug_cmd.finish("调试模式已关闭。" if changed else "调试模式本来就是关闭的。")


@empty_alert_cmd.handle()
async def _handle_empty_alert(args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    action = parse_switch(args.extract_plain_text())
    if action is None:
        await empty_alert_cmd.finish(f"用法：{prefix}红包空提醒 开 / {prefix}红包空提醒 关")
    changed = store.set_empty_alert(action)
    if action:
        await empty_alert_cmd.finish(
            "空消息提醒已开启：被监听群收到无内容消息（疑似红包）时会私聊通知。"
            if changed
            else "空消息提醒本来就是开启的。"
        )
    await empty_alert_cmd.finish("空消息提醒已关闭。" if changed else "空消息提醒本来就是关闭的。")


@affection_top_cmd.handle()
async def _handle_affection_top(args: Message = CommandArg()) -> None:
    prefix = _command_prefix()
    action = parse_switch(args.extract_plain_text())
    if action is None:
        await affection_top_cmd.finish(f"用法：{prefix}红包榜一提醒 开 / {prefix}红包榜一提醒 关")
    changed = store.set_affection_top(action)
    if action:
        await affection_top_cmd.finish(
            "榜一提醒已开启：群内出现红包时，会额外私聊该群好感度榜第一的用户"
            "（需安装 nonebot-plugin-mantou-affection，榜一随好感度榜实时变化）。"
            if changed
            else "榜一提醒本来就是开启的。"
        )
    await affection_top_cmd.finish("榜一提醒已关闭。" if changed else "榜一提醒本来就是关闭的。")
