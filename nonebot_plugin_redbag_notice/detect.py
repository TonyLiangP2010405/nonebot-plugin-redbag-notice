"""红包检测纯函数：从消息段中识别红包特征，便于单测与复用

QQ 客户端的红包以 OneBot V11 ``json`` 消息段下发（NapCat / go-cqhttp 一致），
段内 ``data`` 字段通常是一段被转义的 JSON 字符串，字段名与内容由客户端决定。
因此这里做的是**特征匹配**而不是严格协议解析：

* json 段内容里出现 ``红包`` / ``恭喜发财`` / ``[QQ红包]`` 任一特征词即判为红包；
* 没有任何 json 段命中时，再按纯文本消息兜底（``[QQ红包]``、``口令红包``）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

REDBAG_KEYWORDS: tuple[str, ...] = ("红包", "恭喜发财", "[QQ红包]")
"""json 段中的红包特征词，命中任意一个即视为红包"""

TEXT_KEYWORDS: tuple[str, ...] = ("[QQ红包]", "口令红包")
"""纯文本消息中的红包特征词（仅在没有任何 json 段命中时兜底）"""

PROMPT_KEYS: tuple[str, ...] = ("prompt", "desc", "summary", "title", "wishing", "name")
"""红包提示文本可能出现的字段名，按优先级从上到下排列"""

PROMPT_MAX_LENGTH = 60
"""提取到的提示文本最大长度，超出则截断"""

_FALLBACK_PROMPT_RE = re.compile(r"\[QQ红包\][^\"\\,，。;；]{0,30}")


@dataclass(frozen=True)
class RedbagHit:
    """一次红包命中结果"""

    keyword: str
    """命中的特征词"""

    prompt: str
    """从 json 中提取到的红包提示文本，提取不到时为空串"""

    detail: str
    """命中的完整内容（转义已还原），用于日志与调试输出"""

    source: str
    """命中来源：``json`` 表示 json 消息段，``text`` 表示纯文本消息"""


def stringify(value: Any) -> str:
    """把任意 json 段内容转成字符串（dict / list 转 JSON 文本）"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def normalize_detail(value: Any) -> str:
    """规整 json 段内容：还原 ``\\uXXXX`` 转义与多重编码，得到可读文本

    QQ 下发的 json 段内容可能是字符串形式的 JSON（且非 ASCII 字符被转义），
    直接搜索中文特征词会漏判，因此这里尽量解析并重新序列化。
    """
    text = stringify(value).strip()
    for _ in range(2):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if isinstance(parsed, str):
            text = parsed.strip()
            continue
        return json.dumps(parsed, ensure_ascii=False)
    return text


def find_keyword(text: str, keywords: Sequence[str] = REDBAG_KEYWORDS) -> str:
    """返回文本中命中的第一个特征词，未命中返回空串"""
    if not text:
        return ""
    return next((keyword for keyword in keywords if keyword in text), "")


def iter_json_details(message: Iterable[Any]) -> Iterator[str]:
    """遍历消息段，产出每个 ``json`` 段规整后的内容（跳过空内容）"""
    for segment in message:
        if getattr(segment, "type", None) != "json":
            continue
        data = getattr(segment, "data", None)
        raw = data.get("data") if isinstance(data, dict) else data
        if raw is None:
            raw = data
        detail = normalize_detail(raw)
        if detail:
            yield detail


def _iter_string_fields(payload: Any) -> Iterator[tuple[str, str]]:
    """递归收集 JSON 结构中的所有字符串字段（键值对）"""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str):
                yield str(key), value
            else:
                yield from _iter_string_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_string_fields(item)


def extract_prompt(detail: str) -> str:
    """从命中的 json 段内容里提取红包提示文本，提取不到返回空串"""
    try:
        payload = json.loads(detail)
    except (TypeError, ValueError):
        payload = None

    if payload is not None:
        fields = list(_iter_string_fields(payload))
        for key in PROMPT_KEYS:
            for name, value in fields:
                text = value.strip()
                if text and name.lower() == key:
                    return text[:PROMPT_MAX_LENGTH]
        # 兜底：任何包含“红包”字样的短字符串
        for _, value in fields:
            text = value.strip()
            if text and "红包" in text and len(text) <= PROMPT_MAX_LENGTH:
                return text

    matched = _FALLBACK_PROMPT_RE.search(detail)
    return matched.group(0).strip() if matched else ""


def scan_message(message: Iterable[Any] = (), raw_message: str = "") -> list[RedbagHit]:
    """扫描一条消息，返回所有红包命中结果（json 段优先，纯文本兜底）"""
    hits: list[RedbagHit] = []
    for detail in iter_json_details(message):
        keyword = find_keyword(detail)
        if keyword:
            hits.append(RedbagHit(keyword=keyword, prompt=extract_prompt(detail), detail=detail, source="json"))
    if hits:
        return hits

    keyword = find_keyword(raw_message, TEXT_KEYWORDS)
    if keyword:
        hits.append(RedbagHit(keyword=keyword, prompt="", detail=raw_message.strip(), source="text"))
    return hits


def looks_like_redbag(message: Iterable[Any] = (), raw_message: str = "") -> bool:
    """消息是否疑似红包（``scan_message`` 的布尔封装）"""
    return bool(scan_message(message, raw_message))
