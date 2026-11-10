import logging

import nonebot
# from nonebot.adapters.console import Adapter as ConsoleAdapter
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.qq import Adapter as QQAdapter

# NoneBot 的日志只接了自己的 loguru logger（nonebot/log.py 里 stdlib 桥接被注释掉了），
# 插件里 logging.getLogger(__name__).info(...) 之前无人接管：INFO 被丢弃，
# 只有 WARNING 以上才靠 logging.lastResort 落到 stderr。这里显式配一个 stderr 输出，
# 让插件的 INFO 日志（运行状态、限流、错误详情等）真的可见。
# 需要更安静时把 level 调成 logging.WARNING 即可。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
)

nonebot.init()

driver = nonebot.get_driver()
# driver.register_adapter(ConsoleAdapter)
driver.register_adapter(OneBotV11Adapter)
# 官方机器人是可选部署：.env.secret 里配了 QQ_BOTS 才注册，避免纯 OneBot 环境多一个空适配器
if getattr(driver.config, "qq_bots", []):
    driver.register_adapter(QQAdapter)

from nonebot.message import event_preprocessor

from src.utils.adapter_compat import strip_qq_mentions


@event_preprocessor
async def _strip_qq_mentions(bot, event, state) -> None:
    """官方「全量消息模式」下剥掉 content 里的 <@openid> 占位符。"""
    strip_qq_mentions(event)


nonebot.load_plugins("nonebot_plugin_alconna")
nonebot.load_plugins("nonebot_plugin_localstore")
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()
