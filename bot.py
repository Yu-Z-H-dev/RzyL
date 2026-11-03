import logging

import nonebot
# from nonebot.adapters.console import Adapter as ConsoleAdapter
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

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

nonebot.load_plugins("nonebot_plugin_alconna")
nonebot.load_plugins("nonebot_plugin_localstore")
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()
