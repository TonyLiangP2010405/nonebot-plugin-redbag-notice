"""群消息监听与私聊提醒

群消息监听的优先级很低（90）且 ``block=False``，只在「群在监听列表且提醒名单
非空」时才做检测，命中后给提醒名单中的每个用户单独发一条私聊提醒。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from nonebot import on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.log import logger

from .detect import RedbagHit, scan_message
from .store import get_watchers, is_debug, should_monitor

MAX_RECENT_MESSAGE_IDS = 200
"""最近已提醒消息 ID 的缓存长度，用于去重（防止同一条消息重复提醒）"""

_recent_message_ids: deque[int] = deque(maxlen=MAX_RECENT_MESSAGE_IDS)


def sender_name(event: GroupMessageEvent) -> str:
    """发送者昵称，取不到时退回 QQ 号"""
    sender = getattr(event, "sender", None)
    for field in ("nickname", "card"):
        value = getattr(sender, field, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(event.user_id)


def build_notice(event: GroupMessageEvent, hits: Sequence[RedbagHit]) -> str:
    """组装私聊提醒文本"""
    lines = [
        "【红包提醒】",
        f"群号：{event.group_id}",
        f"发送者：{sender_name(event)}（{event.user_id}）",
    ]
    prompts = list(dict.fromkeys(hit.prompt for hit in hits if hit.prompt))
    if prompts:
        lines.append(f"提示：{' / '.join(prompts)}")
    return "\n".join(lines)


async def notify_watchers(bot: Bot, event: GroupMessageEvent, hits: Sequence[RedbagHit]) -> int:
    """给提醒名单中的每个用户发私聊提醒，返回发送成功的人数

    单个用户发送失败（未加好友、风控等）只记录日志，不影响其他人。
    """
    notice = build_notice(event, hits)
    sent = 0
    for user_id in get_watchers():
        try:
            await bot.send_private_msg(user_id=user_id, message=notice)
        except Exception as error:
            logger.warning(f"红包提醒私聊发送失败：用户 {user_id}（{error!r}）")
        else:
            sent += 1
    return sent


async def handle_group_message(bot: Bot, event: GroupMessageEvent) -> bool:
    """处理一条群消息：命中红包则私聊提醒，返回是否真的触发了提醒"""
    if not should_monitor(event.group_id):
        return False
    if event.message_id in _recent_message_ids:
        return False

    if is_debug():
        segments = [segment.type for segment in event.get_message()]
        logger.info(
            f"红包调试｜群 {event.group_id}｜收到消息 {event.message_id}"
            f"｜段类型 {segments or '（空消息）'}｜raw：{event.raw_message!r}"
        )

    hits = scan_message(event.get_message(), event.raw_message)
    if not hits:
        return False

    _recent_message_ids.append(event.message_id)
    if is_debug():
        for hit in hits:
            logger.info(f"红包调试｜群 {event.group_id}｜消息 {event.message_id}｜来源 {hit.source}\n{hit.detail}")

    sent = await notify_watchers(bot, event, hits)
    logger.info(f"红包提醒：群 {event.group_id} 检测到红包（{hits[0].keyword}），已通知 {sent} 人")
    return True


async def _is_monitored_group_message(event: Event) -> bool:
    """只在被监听的群消息上继续执行检测"""
    return isinstance(event, GroupMessageEvent) and should_monitor(event.group_id)


redbag_monitor = on_message(priority=90, block=False, rule=_is_monitored_group_message)
"""群消息红包监听（低优先级，不阻断其它插件）"""


@redbag_monitor.handle()
async def _handle_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    await handle_group_message(bot, event)
