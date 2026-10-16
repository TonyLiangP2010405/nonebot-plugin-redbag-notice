"""群消息监听与私聊提醒测试

私聊提醒逻辑用假 Bot 直接调用 ``handle_group_message`` 断言；
私聊管理命令则用 nonebug 走真实的事件响应流程。
"""

import json
from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebug import App

from nonebot_plugin_redbag_notice import (
    affection_top_cmd,
    alert_cmd,
    debug_cmd,
    empty_alert_cmd,
    status_cmd,
    status_text,
    store,
    watch_add_cmd,
    watch_del_cmd,
    watch_list_cmd,
)
from nonebot_plugin_redbag_notice import notify as notify_module
from nonebot_plugin_redbag_notice.notify import handle_group_message, redbag_monitor

GROUP_ID = 123456
OTHER_GROUP_ID = 654321
USER_ID = 20001
OTHER_USER_ID = 20002
SUPERUSER_ID = 10001  # 与 conftest 中 nonebot 初始化配置的 superusers 保持一致

REDBAG_JSON = json.dumps(
    {
        "app": "com.tencent.mobileqq.redpacket",
        "desc": "[QQ红包]恭喜发财",
        "prompt": "[QQ红包]恭喜发财",
    },
    ensure_ascii=False,
)


def json_card(detail: str = REDBAG_JSON) -> MessageSegment:
    return MessageSegment.json(detail)


class RecordingBot:
    """只实现 send_private_msg 的假 Bot，用于断言私聊提醒内容"""

    def __init__(self, fail_for=()):
        self.sent: list[tuple[int, str]] = []
        self._fail_for = set(fail_for)

    async def send_private_msg(self, user_id, message, **kwargs):
        if user_id in self._fail_for:
            raise RuntimeError("模拟发送失败")
        self.sent.append((user_id, message))
        return {"message_id": len(self.sent)}


# ---------------------------------------------------------------------------
# 群消息 → 私聊提醒
# ---------------------------------------------------------------------------


async def test_notifies_all_watchers(data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.add_user(OTHER_USER_ID)
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True

    assert [user_id for user_id, _ in bot.sent] == [USER_ID, OTHER_USER_ID]
    assert bot.sent[0][1] == (
        "【红包提醒】\n群号：123456\n发送者：测试群友（20001）\n提示：[QQ红包]恭喜发财"
    )


async def test_duplicate_message_notified_once(data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RecordingBot()
    event = group_event(json_card())

    assert await handle_group_message(bot, event) is True
    assert await handle_group_message(bot, event) is False
    assert len(bot.sent) == 1


async def test_unwatched_group_skipped(data_dir, group_event):
    store.add_user(USER_ID)  # 有提醒名单，但群没有加入监听
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is False
    assert bot.sent == []


async def test_empty_watch_list_skipped(data_dir, group_event):
    store.add_group(GROUP_ID)  # 群已监听，但没人接收提醒
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is False
    assert bot.sent == []


async def test_non_redbag_message_skipped(data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RecordingBot()

    normal_card = json_card(json.dumps({"app": "com.tencent.structmsg", "desc": "一起来听歌"}))
    assert await handle_group_message(bot, group_event("今天天气不错")) is False
    assert await handle_group_message(bot, group_event(normal_card)) is False
    assert bot.sent == []


async def test_text_redbag_notified(data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event("[QQ红包]恭喜发财")) is True
    assert bot.sent[0][1].startswith("【红包提醒】\n群号：123456")
    assert "提示：" not in bot.sent[0][1]  # 纯文本命中没有提示文本


async def test_send_failure_does_not_block_others(data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.add_user(OTHER_USER_ID)
    bot = RecordingBot(fail_for={USER_ID})

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [OTHER_USER_ID]


class RefetchBot(RecordingBot):
    """带 get_msg 的假 Bot，模拟 NapCat 上报空消息但接口能拉到完整内容"""

    def __init__(self, refetch_result=None, **kwargs):
        super().__init__(**kwargs)
        self.refetch_result = refetch_result
        self.refetch_calls = 0

    async def get_msg(self, message_id, **kwargs):
        self.refetch_calls += 1
        if isinstance(self.refetch_result, Exception):
            raise self.refetch_result
        return self.refetch_result


async def test_empty_message_refetched_and_notified(data_dir, group_event):
    """NapCat 上报空 text 段时，通过 get_msg 重拉到 json 段并正常提醒"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RefetchBot(
        refetch_result={
            "message": [{"type": "json", "data": {"data": REDBAG_JSON}}],
            "raw_message": "",
        }
    )

    assert await handle_group_message(bot, group_event("")) is True
    assert bot.refetch_calls == 1
    assert bot.sent[0][1].startswith("【红包提醒】\n群号：123456")


async def test_empty_message_refetch_also_empty(data_dir, group_event):
    """重拉后仍然没有内容时不提醒"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RefetchBot(refetch_result={"message": [{"type": "text", "data": {"text": ""}}], "raw_message": ""})

    assert await handle_group_message(bot, group_event("")) is False
    assert bot.sent == []


async def test_empty_alert_notifies_on_unresolvable_empty_message(data_dir, group_event):
    """开启空消息提醒后，重拉仍为空的 NapCat 红包按疑似红包通知"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_empty_alert(True)
    bot = RefetchBot(refetch_result={"message": [{"type": "text", "data": {"text": ""}}], "raw_message": ""})

    assert await handle_group_message(bot, group_event("")) is True
    assert bot.refetch_calls == 1
    assert "疑似红包" in bot.sent[0][1]

    # 同一条消息不重复提醒
    assert await handle_group_message(bot, group_event("")) is False
    assert len(bot.sent) == 1


async def test_empty_message_refetch_failure_ignored(data_dir, group_event):
    """get_msg 调用失败只记日志，不影响流程"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RefetchBot(refetch_result=RuntimeError("模拟接口失败"))

    assert await handle_group_message(bot, group_event("")) is False
    assert bot.sent == []


async def test_normal_message_does_not_refetch(data_dir, group_event):
    """有内容的消息不会触发重拉"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    bot = RefetchBot()

    assert await handle_group_message(bot, group_event("今天天气不错")) is False
    assert bot.refetch_calls == 0


# ---------------------------------------------------------------------------
# 好感榜一联动（nonebot-plugin-mantou-affection）
# ---------------------------------------------------------------------------


class FakeMantouStore:
    """模拟 mantou-affection 的 AffectionStore.ranking 接口"""

    def __init__(self, entries=(), error=None):
        self.entries = list(entries)  # [(user_id, affection), ...] 已按榜单顺序
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def ranking(self, group_id, limit):
        self.calls.append((group_id, limit))
        if self.error:
            raise self.error
        return [
            SimpleNamespace(rank=index + 1, profile=SimpleNamespace(user_id=str(user_id), affection=affection))
            for index, (user_id, affection) in enumerate(self.entries[:limit])
        ]


def patch_mantou(monkeypatch, mantou_store):
    from nonebot_plugin_redbag_notice import notify

    monkeypatch.setattr(notify, "_load_mantou_store", lambda: mantou_store)


async def test_affection_top_user_also_notified(data_dir, group_event, monkeypatch):
    """开启榜一提醒后，好感榜一会与提醒名单一起收到通知"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    fake = FakeMantouStore(entries=[(OTHER_USER_ID, 10)])
    patch_mantou(monkeypatch, fake)
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID, OTHER_USER_ID]
    assert fake.calls == [(str(GROUP_ID), notify_module.TOP_RANKING_SCAN_LIMIT)]


async def test_affection_top_tied_users_all_notified(data_dir, group_event, monkeypatch):
    """好感度相同的并列榜一全部收到通知，第二名不收到"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    fake = FakeMantouStore(entries=[(20002, 10), (20003, 10), (20004, 5)])
    patch_mantou(monkeypatch, fake)
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID, 20002, 20003]


async def test_affection_top_dedup_with_watchers(data_dir, group_event, monkeypatch):
    """榜一已在提醒名单中时只发一条"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    patch_mantou(monkeypatch, FakeMantouStore(entries=[(USER_ID, 10)]))
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID]


async def test_affection_top_disabled_skips_query(data_dir, group_event, monkeypatch):
    """未开启榜一提醒时不查询好感榜"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    monkeypatch.setattr(
        notify_module, "_load_mantou_store", lambda: pytest.fail("不应加载 mantou 插件")
    )
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID]


async def test_affection_top_without_mantou_installed(data_dir, group_event, monkeypatch):
    """mantou 插件未安装（加载返回 None）时按普通名单提醒"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    patch_mantou(monkeypatch, None)
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID]


async def test_affection_top_ranking_failure_ignored(data_dir, group_event, monkeypatch):
    """好感榜查询失败只记日志，不影响普通提醒"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    patch_mantou(monkeypatch, FakeMantouStore(error=RuntimeError("模拟查询失败")))
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID]


async def test_affection_top_no_ranking_data(data_dir, group_event, monkeypatch):
    """该群还没有好感度数据时按普通名单提醒"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_affection_top(True)
    patch_mantou(monkeypatch, FakeMantouStore())
    bot = RecordingBot()

    assert await handle_group_message(bot, group_event(json_card())) is True
    assert [user_id for user_id, _ in bot.sent] == [USER_ID]


async def test_debug_mode_dumps_raw_json(data_dir, group_event):
    from nonebot.log import logger

    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(str(message)), level="INFO")
    try:
        store.add_group(GROUP_ID)
        store.add_user(USER_ID)
        store.set_debug(True)
        await handle_group_message(RecordingBot(), group_event(json_card()))
    finally:
        logger.remove(sink_id)

    assert any("红包调试" in record and "redpacket" in record for record in records)


async def test_monitor_rule_only_passes_for_monitored_group(app: App, data_dir, group_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)

    async with app.test_matcher(redbag_monitor) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        ctx.receive_event(bot, group_event("中午吃什么", group_id=OTHER_GROUP_ID))
        ctx.should_not_pass_rule(redbag_monitor)


async def test_monitor_notifies_watchers_end_to_end(app: App, data_dir, group_event):
    """走真实响应流程：群消息 → 规则 → 处理函数 → 私聊 API"""
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)

    async with app.test_matcher(redbag_monitor) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        ctx.receive_event(bot, group_event(json_card()))
        ctx.should_pass_rule(redbag_monitor)
        ctx.should_call_api(
            "send_private_msg",
            {
                "user_id": USER_ID,
                "message": "【红包提醒】\n群号：123456\n发送者：测试群友（20001）\n提示：[QQ红包]恭喜发财",
            },
            result=None,
        )


async def test_commands_ignored_in_group(app: App, data_dir, group_event):
    """命令只在私聊生效：群里的同名单词既不通过权限，也不满足规则"""
    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        ctx.receive_event(bot, group_event(f"监听 {GROUP_ID}"))
        ctx.should_not_pass_permission(watch_add_cmd)

    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        ctx.receive_event(bot, group_event(f"监听 {GROUP_ID}", user_id=SUPERUSER_ID))
        ctx.should_not_pass_rule(watch_add_cmd)

    assert store.get_groups() == []


async def test_command_prefix_is_not_ambiguous(app: App, data_dir, private_event):
    """「监听列表」不会被「监听」命令截获，反之亦然"""
    async with app.test_matcher([watch_add_cmd, watch_list_cmd]) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("监听列表")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "当前没有监听任何群。", result=None, bot=bot)
        ctx.should_finished(watch_list_cmd)

    async with app.test_matcher([watch_add_cmd, watch_list_cmd]) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event(f"监听 {GROUP_ID}")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            f"已开始监听群 {GROUP_ID}，群内出现红包时会私聊通知提醒名单中的用户。",
            result=None,
            bot=bot,
        )
        ctx.should_finished(watch_add_cmd)


# ---------------------------------------------------------------------------
# 私聊管理命令（nonebug 事件流）
# ---------------------------------------------------------------------------


async def test_superuser_can_add_group(app: App, data_dir, private_event):
    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event(f"监听 {GROUP_ID}")
        ctx.receive_event(bot, event)
        ctx.should_pass_permission(watch_add_cmd)
        ctx.should_call_send(
            event,
            "已开始监听群 123456，群内出现红包时会私聊通知提醒名单中的用户。",
            result=None,
            bot=bot,
        )
        ctx.should_finished(watch_add_cmd)

    assert store.get_groups() == [GROUP_ID]


async def test_non_superuser_cannot_add_group(app: App, data_dir, private_event):
    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event(f"监听 {GROUP_ID}", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_not_pass_permission(watch_add_cmd)

    assert store.get_groups() == []


async def test_add_group_without_argument(app: App, data_dir, private_event):
    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("监听")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "用法：监听 <群号>\n例如：监听 123456", result=None, bot=bot)
        ctx.should_finished(watch_add_cmd)


async def test_add_group_with_invalid_argument(app: App, data_dir, private_event):
    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("监听 123")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "群号应为 5~12 位数字，请检查后重试。", result=None, bot=bot)
        ctx.should_finished(watch_add_cmd)

    assert store.get_groups() == []


async def test_add_existing_group(app: App, data_dir, private_event):
    store.add_group(GROUP_ID)

    async with app.test_matcher(watch_add_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event(f"监听 {GROUP_ID}")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, f"群 {GROUP_ID} 已在监听列表中。", result=None, bot=bot)
        ctx.should_finished(watch_add_cmd)


async def test_remove_group(app: App, data_dir, private_event):
    store.add_group(GROUP_ID)

    async with app.test_matcher(watch_del_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event(f"取消监听 {GROUP_ID}")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, f"已取消监听群 {GROUP_ID}。", result=None, bot=bot)
        ctx.should_finished(watch_del_cmd)

    assert store.get_groups() == []


async def test_watch_list_empty(app: App, data_dir, private_event):
    async with app.test_matcher(watch_list_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("监听列表")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "当前没有监听任何群。", result=None, bot=bot)
        ctx.should_finished(watch_list_cmd)


async def test_watch_list_shows_groups(app: App, data_dir, private_event):
    store.add_group(GROUP_ID)
    store.add_group(OTHER_GROUP_ID)

    async with app.test_matcher(watch_list_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("监听列表")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            f"共监听 2 个群：\n{GROUP_ID}、{OTHER_GROUP_ID}",
            result=None,
            bot=bot,
        )
        ctx.should_finished(watch_list_cmd)


async def test_anyone_can_toggle_alert(app: App, data_dir, private_event):
    async with app.test_matcher(alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包提醒 开", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_pass_permission(alert_cmd)
        ctx.should_call_send(event, "已开启红包提醒，群内出现红包时会私聊通知你。", result=None, bot=bot)
        ctx.should_finished(alert_cmd)

    assert store.get_watchers() == [OTHER_USER_ID]

    async with app.test_matcher(alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包提醒 关", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "已关闭红包提醒。", result=None, bot=bot)
        ctx.should_finished(alert_cmd)

    assert store.get_watchers() == []


async def test_alert_without_argument(app: App, data_dir, private_event):
    async with app.test_matcher(alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包提醒")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            "用法：红包提醒 开 —— 收到红包时私聊通知我\n　　　红包提醒 关 —— 不再接收红包通知",
            result=None,
            bot=bot,
        )
        ctx.should_finished(alert_cmd)

    assert store.get_watchers() == []


async def test_debug_switch(app: App, data_dir, private_event):
    async with app.test_matcher(debug_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包调试 开")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "调试模式已开启：命中红包时会把原始 json 段写入日志。", result=None, bot=bot)
        ctx.should_finished(debug_cmd)

    assert store.is_debug() is True


async def test_debug_switch_requires_superuser(app: App, data_dir, private_event):
    async with app.test_matcher(debug_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包调试 开", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_not_pass_permission(debug_cmd)

    assert store.is_debug() is False


async def test_empty_alert_switch(app: App, data_dir, private_event):
    async with app.test_matcher(empty_alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包空提醒 开")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            "空消息提醒已开启：被监听群收到无内容消息（疑似红包）时会私聊通知。",
            result=None,
            bot=bot,
        )
        ctx.should_finished(empty_alert_cmd)

    assert store.is_empty_alert() is True

    async with app.test_matcher(empty_alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包空提醒 关")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "空消息提醒已关闭。", result=None, bot=bot)
        ctx.should_finished(empty_alert_cmd)

    assert store.is_empty_alert() is False


async def test_empty_alert_switch_requires_superuser(app: App, data_dir, private_event):
    async with app.test_matcher(empty_alert_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包空提醒 开", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_not_pass_permission(empty_alert_cmd)

    assert store.is_empty_alert() is False


async def test_affection_top_switch(app: App, data_dir, private_event):
    async with app.test_matcher(affection_top_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包榜一提醒 开")
        ctx.receive_event(bot, event)
        ctx.should_call_send(
            event,
            "榜一提醒已开启：群内出现红包时，会额外私聊该群好感度榜第一（含并列）的用户"
            "（需安装 nonebot-plugin-mantou-affection，榜一随好感度榜实时变化）。",
            result=None,
            bot=bot,
        )
        ctx.should_finished(affection_top_cmd)

    assert store.is_affection_top() is True

    async with app.test_matcher(affection_top_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包榜一提醒 关")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, "榜一提醒已关闭。", result=None, bot=bot)
        ctx.should_finished(affection_top_cmd)

    assert store.is_affection_top() is False


async def test_affection_top_switch_requires_superuser(app: App, data_dir, private_event):
    async with app.test_matcher(affection_top_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包榜一提醒 开", user_id=OTHER_USER_ID)
        ctx.receive_event(bot, event)
        ctx.should_not_pass_permission(affection_top_cmd)

    assert store.is_affection_top() is False


async def test_status_command(app: App, data_dir, private_event):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)

    async with app.test_matcher(status_cmd) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="99999")
        event = private_event("红包监听")
        ctx.receive_event(bot, event)
        ctx.should_call_send(event, status_text(), result=None, bot=bot)
        ctx.should_finished(status_cmd)


def test_status_text_content(data_dir):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_debug(True)

    text = status_text()
    assert f"监听群（1 个）：{GROUP_ID}" in text
    assert f"提醒用户（1 人）：{USER_ID}" in text
    assert "调试模式：开启" in text
    assert "空消息提醒：关闭" in text
    assert "数据文件：" in text
    assert "监听群为空时不会监听任何群。" in text


def test_command_prefix_follows_config(monkeypatch):
    """帮助文本里的命令前缀跟随 NoneBot 的 command_start 配置"""
    from nonebot import get_driver

    from nonebot_plugin_redbag_notice import _command_prefix

    assert _command_prefix() == ""  # 测试配置为 {""}
    monkeypatch.setattr(get_driver().config, "command_start", {"/"}, raising=False)
    assert _command_prefix() == "/"
