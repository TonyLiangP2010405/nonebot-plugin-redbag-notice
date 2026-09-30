"""插件加载与注册冒烟"""

import nonebot


def test_plugin_loaded():
    plugin = nonebot.get_plugin("nonebot_plugin_redbag_notice")
    assert plugin is not None
    assert plugin.metadata is not None
    assert plugin.metadata.name == "红包提醒"
    assert plugin.metadata.supported_adapters == {"~onebot.v11"}


def test_zero_config_import():
    """没有配置任何 .env 项时，配置模型给得出默认值"""
    from nonebot_plugin_redbag_notice.config import Config

    config = Config()
    assert config.redbag_notice_data_dir == ""


def test_matchers_registered():
    """6 个命令响应器 + 1 个群消息监听都挂在插件上"""
    from nonebot_plugin_redbag_notice import (
        alert_cmd,
        debug_cmd,
        status_cmd,
        watch_add_cmd,
        watch_del_cmd,
        watch_list_cmd,
    )
    from nonebot_plugin_redbag_notice.notify import redbag_monitor

    plugin = nonebot.get_plugin("nonebot_plugin_redbag_notice")
    assert plugin is not None
    for matcher in (status_cmd, watch_add_cmd, watch_del_cmd, watch_list_cmd, alert_cmd, debug_cmd, redbag_monitor):
        assert matcher in plugin.matcher


def test_monitor_is_low_priority_and_not_blocking():
    from nonebot_plugin_redbag_notice.notify import redbag_monitor

    assert redbag_monitor.priority == 90
    assert redbag_monitor.block is False
