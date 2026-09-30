"""红包检测纯函数单测"""

import json

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from nonebot_plugin_redbag_notice.detect import (
    extract_prompt,
    find_keyword,
    looks_like_redbag,
    normalize_detail,
    scan_message,
)

REDBAG_JSON = json.dumps(
    {
        "app": "com.tencent.mobileqq.redpacket",
        "bizsrc": "",
        "config": {"forward": 1},
        "desc": "[QQ红包]恭喜发财",
        "meta": {"detail": {"icon": "http://example.com/hb.png", "title": "恭喜发财", "type": "1"}},
        "prompt": "[QQ红包]恭喜发财",
        "view": "NativeQQHongbao",
    },
    ensure_ascii=False,
)
"""模拟 NapCat 上报的 QQ 红包 json 段内容"""

NORMAL_JSON = json.dumps(
    {
        "app": "com.tencent.structmsg",
        "desc": "一起来听歌",
        "meta": {"music": {"title": "测试歌曲", "desc": "测试歌手"}},
        "prompt": "[分享]测试歌曲",
        "view": "music",
    },
    ensure_ascii=False,
)
"""一段普通（非红包）的 json 卡片"""


def json_message(detail: str) -> Message:
    """构造只包含一个 json 段的消息"""
    return Message(MessageSegment.json(detail))


class TestNormalizeDetail:
    def test_plain_json_kept(self):
        assert json.loads(normalize_detail(REDBAG_JSON))["prompt"] == "[QQ红包]恭喜发财"

    def test_unicode_escape_restored(self):
        """QQ 有时把 json 段内容二次编码，中文变成 \\uXXXX 转义"""
        double_encoded = json.dumps(REDBAG_JSON)
        assert "\\u7ea2\\u5305" in double_encoded
        assert "红包" in normalize_detail(double_encoded)

    def test_dict_and_none(self):
        assert json.loads(normalize_detail({"prompt": "恭喜发财"}))["prompt"] == "恭喜发财"
        assert normalize_detail(None) == ""
        assert normalize_detail("不是 json") == "不是 json"


class TestFindKeyword:
    def test_hits(self):
        assert find_keyword("这是一段红包描述") == "红包"
        assert find_keyword("恭喜发财，大吉大利") == "恭喜发财"
        assert find_keyword("[QQ红包]") == "红包"

    def test_miss(self):
        assert find_keyword("一起来听歌") == ""
        assert find_keyword("") == ""


class TestExtractPrompt:
    def test_prefers_prompt_field(self):
        payload = json.dumps({"title": "恭喜发财", "prompt": "大吉大利"}, ensure_ascii=False)
        assert extract_prompt(payload) == "大吉大利"

    def test_falls_back_to_desc(self):
        payload = json.dumps({"desc": "恭喜发财，大吉大利"}, ensure_ascii=False)
        assert extract_prompt(payload) == "恭喜发财，大吉大利"

    def test_falls_back_to_any_redbag_field(self):
        payload = json.dumps({"unknown": "恭喜发财的红包"}, ensure_ascii=False)
        assert extract_prompt(payload) == "恭喜发财的红包"

    def test_truncated(self):
        payload = json.dumps({"prompt": "红" * 100}, ensure_ascii=False)
        assert len(extract_prompt(payload)) == 60

    def test_empty_when_nothing_found(self):
        assert extract_prompt(json.dumps({"app": "com.tencent.mobileqq.redpacket"})) == ""
        assert extract_prompt("不是 json") == ""


class TestScanMessage:
    def test_redbag_json_hit(self):
        hits = scan_message(json_message(REDBAG_JSON), raw_message=f"[CQ:json,data={REDBAG_JSON}]")
        assert len(hits) == 1
        assert hits[0].source == "json"
        assert hits[0].keyword == "红包"
        assert hits[0].prompt == "[QQ红包]恭喜发财"
        assert "com.tencent.mobileqq.redpacket" in hits[0].detail

    def test_escaped_redbag_json_hit(self):
        """二次编码（中文被转义）的红包卡片同样能命中"""
        hits = scan_message(json_message(json.dumps(REDBAG_JSON)))
        assert len(hits) == 1
        assert hits[0].prompt == "[QQ红包]恭喜发财"

    def test_dict_data_hit(self):
        segment = MessageSegment("json", {"data": {"app": "com.tencent.mobileqq.redpacket", "prompt": "恭喜发财"}})
        hits = scan_message(Message(segment))
        assert len(hits) == 1
        assert hits[0].prompt == "恭喜发财"

    def test_normal_json_card_missed(self):
        message = json_message(NORMAL_JSON)
        assert scan_message(message, raw_message=str(message)) == []
        assert looks_like_redbag(message) is False

    def test_text_redbag_hit(self):
        text = "[QQ红包]恭喜发财，大吉大利"
        hits = scan_message(Message(text), raw_message=text)
        assert len(hits) == 1
        assert hits[0].source == "text"
        assert hits[0].keyword == "[QQ红包]"
        assert hits[0].prompt == ""

    def test_kouling_redbag_text_hit(self):
        text = "口令红包：恭喜发财"
        hits = scan_message(Message(text), raw_message=text)
        assert len(hits) == 1
        assert hits[0].keyword == "口令红包"

    def test_plain_chat_missed(self):
        text = "刚才那个红包我抢到 0.01 元"
        assert scan_message(Message(text), raw_message=text) == []
        assert scan_message(Message("恭喜发财")) == []

    def test_json_hit_wins_over_text(self):
        """json 段命中时不再看纯文本，避免同一条消息被重复计数"""
        message = Message(MessageSegment.json(REDBAG_JSON))
        hits = scan_message(message, raw_message="口令红包：恭喜发财")
        assert len(hits) == 1
        assert hits[0].source == "json"

    def test_non_json_segments_ignored(self):
        message = Message(MessageSegment.image("http://example.com/a.png") + MessageSegment.text("看图"))
        assert scan_message(message, raw_message=str(message)) == []

    def test_empty_message(self):
        assert scan_message(Message(), raw_message="") == []
