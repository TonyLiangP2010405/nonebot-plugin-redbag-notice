"""监听配置读写单测"""

import json

from nonebot_plugin_redbag_notice import store

GROUP_ID = 123456
OTHER_GROUP_ID = 654321
USER_ID = 20001
OTHER_USER_ID = 20002


def settings_path(data_dir):
    return data_dir / "settings.json"


def test_defaults_when_file_missing(data_dir):
    settings = store.load_settings()
    assert settings.groups == []
    assert settings.users == []
    assert settings.debug is False
    assert not settings_path(data_dir).exists()
    assert store.should_monitor(GROUP_ID) is False


def test_group_add_and_remove(data_dir):
    assert store.add_group(GROUP_ID) is True
    assert store.add_group(GROUP_ID) is False
    assert store.add_group(OTHER_GROUP_ID) is True
    assert store.get_groups() == [GROUP_ID, OTHER_GROUP_ID]
    assert store.is_watched_group(GROUP_ID) is True
    assert store.is_watched_group(999999) is False
    assert json.loads(settings_path(data_dir).read_text(encoding="utf-8"))["groups"] == [GROUP_ID, OTHER_GROUP_ID]

    assert store.remove_group(GROUP_ID) is True
    assert store.remove_group(GROUP_ID) is False
    assert store.get_groups() == [OTHER_GROUP_ID]


def test_user_add_and_remove(data_dir):
    assert store.add_user(USER_ID) is True
    assert store.add_user(USER_ID) is False
    assert store.get_watchers() == [USER_ID]

    assert store.remove_user(USER_ID) is True
    assert store.remove_user(USER_ID) is False
    assert store.get_watchers() == []


def test_debug_switch(data_dir):
    assert store.is_debug() is False
    assert store.set_debug(True) is True
    assert store.is_debug() is True
    assert store.set_debug(True) is False
    assert store.set_debug(False) is True
    assert store.is_debug() is False


def test_should_monitor_needs_group_and_watchers(data_dir):
    store.add_group(GROUP_ID)
    assert store.should_monitor(GROUP_ID) is False  # 提醒名单为空 → 不监听

    store.add_user(USER_ID)
    assert store.should_monitor(GROUP_ID) is True
    assert store.should_monitor(OTHER_GROUP_ID) is False  # 群不在监听列表

    store.remove_group(GROUP_ID)
    assert store.should_monitor(GROUP_ID) is False


def test_settings_persisted_between_reads(data_dir):
    store.add_group(GROUP_ID)
    store.add_user(USER_ID)
    store.set_debug(True)

    raw = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    assert raw == {"groups": [GROUP_ID], "users": [USER_ID], "debug": True}
    assert store.load_settings().model_dump() == raw


def test_corrupted_file_falls_back_to_defaults(data_dir):
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是 json", encoding="utf-8")

    assert store.load_settings().groups == []
    # 坏文件不会阻止后续写入
    assert store.add_group(GROUP_ID) is True
    assert store.get_groups() == [GROUP_ID]


def test_data_dir_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    monkeypatch.setattr(store, "_data_dir_override", lambda: str(custom))
    assert store.get_data_dir() == custom
    assert store.get_data_file() == custom / "settings.json"


def test_data_dir_defaults_to_localstore(monkeypatch):
    """未配置覆盖时使用 nonebot-plugin-localstore 的插件数据目录"""
    monkeypatch.setattr(store, "_data_dir_override", lambda: "")
    data_dir = store.get_data_dir()
    assert data_dir.name == "nonebot_plugin_redbag_notice"
    assert store.get_data_file() == data_dir / "settings.json"
