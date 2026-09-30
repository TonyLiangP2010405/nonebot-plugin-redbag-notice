"""pytest 全局配置

用 nonebug 的 ``none`` 驱动初始化 nonebot，并在 ``pytest_configure`` 中加载插件：
插件必须在测试模块导入前加载，否则测试模块的 ``import`` 会先把插件包写进
``sys.modules``，导致之后 ``nonebot.load_plugin`` 拿不到 ``__plugin__`` 而失败。

测试配置里把 ``command_start`` 设为空集合，这样命令可以不带前缀书写（``监听 123456``）。
"""

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebug import NONEBOT_INIT_KWARGS

NONEBOT_INIT = {
    "driver": "~none",
    "command_start": {""},
    "superusers": {"10001"},
}

SUPERUSER_ID = 10001
"""超管 QQ（与 NONEBOT_INIT 中的 superusers 保持一致）"""

GROUP_ID = 123456
"""测试用群号"""


def pytest_configure(config: pytest.Config) -> None:
    config.stash[NONEBOT_INIT_KWARGS] = NONEBOT_INIT
    nonebot.init(**NONEBOT_INIT)
    nonebot.get_driver().register_adapter(OneBotV11Adapter)
    nonebot.load_plugin("nonebot_plugin_redbag_notice")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """把插件数据目录重定向到临时目录，并清空去重缓存，保证用例互不影响"""
    from nonebot_plugin_redbag_notice import notify, store

    monkeypatch.setattr(store, "_data_dir_override", lambda: str(tmp_path))
    notify._recent_message_ids.clear()
    return tmp_path


@pytest.fixture
def private_event():
    """构造私聊消息事件"""

    def _make(message, *, user_id=SUPERUSER_ID, message_id=1, nickname="测试用户"):
        from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent
        from nonebot.adapters.onebot.v11.event import Sender

        return PrivateMessageEvent(
            time=1700000000,
            self_id=99999,
            post_type="message",
            message_type="private",
            sub_type="friend",
            message_id=message_id,
            user_id=user_id,
            message=Message(message),
            original_message=Message(message),
            raw_message=str(message),
            font=0,
            sender=Sender(user_id=user_id, nickname=nickname),
        )

    return _make


@pytest.fixture
def group_event():
    """构造群聊消息事件"""

    def _make(message, *, user_id=20001, group_id=GROUP_ID, message_id=1, nickname="测试群友"):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
        from nonebot.adapters.onebot.v11.event import Sender

        return GroupMessageEvent(
            time=1700000000,
            self_id=99999,
            post_type="message",
            message_type="group",
            sub_type="normal",
            message_id=message_id,
            user_id=user_id,
            group_id=group_id,
            message=Message(message),
            original_message=Message(message),
            raw_message=str(message),
            font=0,
            sender=Sender(user_id=user_id, nickname=nickname, role="member"),
        )

    return _make
