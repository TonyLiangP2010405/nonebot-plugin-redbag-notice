"""插件配置"""

from pydantic import BaseModel


class Config(BaseModel):
    """红包提醒插件配置，全部有默认值，零配置即可用"""

    redbag_notice_data_dir: str = ""
    """监听配置存储目录，留空则使用 nonebot-plugin-localstore 的插件数据目录"""
