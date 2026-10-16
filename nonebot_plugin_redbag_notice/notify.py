"""群消息监听与私聊提醒

群消息监听的优先级很低（90）且 ``block=False``，只在「群在监听列表且提醒名单
非空」时才做检测，命中后给提醒名单中的每个用户单独发一条私聊提醒。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from nonebot import on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.log import logger

from .detect import RedbagHit, scan_message
from .store import get_watchers, is_affection_top, is_debug, is_empty_alert, should_monitor

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


async def notify_watchers(
    bot: Bot, event: GroupMessageEvent, hits: Sequence[RedbagHit], extra_users: Sequence[int] = ()
) -> int:
    """给提醒名单（及额外用户）中的每个人发私聊提醒，返回发送成功的人数

    单个用户发送失败（未加好友、风控等）只记录日志，不影响其他人。
    """
    notice = build_notice(event, hits)
    sent = 0
    for user_id in dict.fromkeys([*get_watchers(), *extra_users]):
        try:
            await bot.send_private_msg(user_id=user_id, message=notice)
        except Exception as error:
            logger.warning(f"红包提醒私聊发送失败：用户 {user_id}（{error!r}）")
        else:
            sent += 1
    return sent


def _load_mantou_store():
    """加载 nonebot-plugin-mantou-affection 的存储实例；未安装或结构不符时返回 None"""
    try:
        return require("nonebot_plugin_mantou_affection").store
    except Exception:
        return None


def is_empty_content(message: Message, raw_message: str) -> bool:
    """消息是否没有任何可检测内容（空 text 段、无消息段、raw 为空）"""
    return not str(message).strip() and not raw_message.strip()


TOP_RANKING_SCAN_LIMIT = 50
"""好感榜查询条数上限，用于收集与榜一好感度相同的并列用户"""


async def affection_top_users(group_id: int) -> list[int]:
    """该群好感度榜一（含并列）的用户 QQ 列表（联动 nonebot-plugin-mantou-affection）

    好感度与第一名相同的用户都算并列榜一，全部返回。
    联动未开启、mantou 插件未安装、该群暂无好感度数据或查询失败时返回空列表。
    """
    if not is_affection_top():
        return []
    store = _load_mantou_store()
    if store is None:
        return []
    try:
        entries = await store.ranking(str(group_id), TOP_RANKING_SCAN_LIMIT)
    except Exception as error:
        logger.warning(f"红包提醒：查询群 {group_id} 好感度榜失败（{error!r}）")
        return []
    if not entries:
        return []
    top_affection = entries[0].profile.affection
    users: list[int] = []
    for entry in entries:
        if entry.profile.affection != top_affection:
            break
        try:
            users.append(int(entry.profile.user_id))
        except (TypeError, ValueError):
            continue
    return users


async def refetch_message(bot: Bot, message_id: int) -> tuple[Message, str] | None:
    """消息内容为空时，通过 ``get_msg`` 重新拉取一次完整消息

    部分实现（如个别 NapCat 版本）上报红包等特殊消息时只给出一个空 text 段，
    但 ``get_msg`` 接口可能返回包含 json 段的完整内容，因此空消息值得重拉一次。
    拉取失败或返回中没有任何内容时返回 ``None``。
    """
    try:
        data = await bot.get_msg(message_id=message_id)
    except Exception as error:
        logger.warning(f"红包提醒：重新拉取消息 {message_id} 失败（{error!r}）")
        return None
    message = data.get("message")
    raw = data.get("raw_message")
    if isinstance(message, list):
        parsed = Message(MessageSegment(**item) if isinstance(item, dict) else item for item in message)
    elif message is not None:
        parsed = Message(message)
    elif isinstance(raw, str):
        parsed = Message(raw)
    else:
        return None
    raw_text = raw if isinstance(raw, str) else parsed.extract_plain_text()
    return parsed, raw_text


async def handle_group_message(bot: Bot, event: GroupMessageEvent) -> bool:
    """处理一条群消息：命中红包则私聊提醒，返回是否真的触发了提醒"""
    if not should_monitor(event.group_id):
        return False
    if event.message_id in _recent_message_ids:
        return False

    message = event.get_message()
    raw_message = event.raw_message
    if is_debug():
        segments = [segment.type for segment in message]
        logger.info(
            f"红包调试｜群 {event.group_id}｜收到消息 {event.message_id}"
            f"｜段类型 {segments or '（空消息）'}｜raw：{raw_message!r}"
        )

    if is_empty_content(message, raw_message):
        refetched = await refetch_message(bot, event.message_id)
        if refetched is not None:
            message, raw_message = refetched
            if is_debug():
                segments = [segment.type for segment in message]
                logger.info(
                    f"红包调试｜群 {event.group_id}｜消息 {event.message_id} 重新拉取"
                    f"｜段类型 {segments or '（空消息）'}｜raw：{raw_message!r}"
                )

    if is_empty_content(message, raw_message):
        # 重拉后仍无内容：协议端未解析出消息（NapCat 下红包即如此），按配置兜底
        if not is_empty_alert():
            return False
        hits = [
            RedbagHit(
                keyword="空消息兜底",
                prompt="协议端未解析出消息内容，疑似红包",
                detail="（消息无内容）",
                source="empty",
            )
        ]
    else:
        hits = scan_message(message, raw_message)
        if not hits:
            return False

    _recent_message_ids.append(event.message_id)
    if is_debug():
        for hit in hits:
            logger.info(f"红包调试｜群 {event.group_id}｜消息 {event.message_id}｜来源 {hit.source}\n{hit.detail}")

    top_users = await affection_top_users(event.group_id)
    sent = await notify_watchers(bot, event, hits, extra_users=top_users)
    top_note = f"（含好感榜一 {'、'.join(str(user) for user in top_users)}）" if top_users else ""
    logger.info(f"红包提醒：群 {event.group_id} 检测到红包（{hits[0].keyword}），已通知 {sent} 人{top_note}")
    return True


async def _is_monitored_group_message(event: Event) -> bool:
    """只在被监听的群消息上继续执行检测"""
    return isinstance(event, GroupMessageEvent) and should_monitor(event.group_id)


redbag_monitor = on_message(priority=90, block=False, rule=_is_monitored_group_message)
"""群消息红包监听（低优先级，不阻断其它插件）"""


@redbag_monitor.handle()
async def _handle_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    await handle_group_message(bot, event)
