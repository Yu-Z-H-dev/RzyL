import nonebot
# from nonebot.adapters.console import Adapter as ConsoleAdapter
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()

driver = nonebot.get_driver()
# driver.register_adapter(ConsoleAdapter)
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins("nonebot_plugin_alconna")
nonebot.load_plugins("nonebot_plugin_localstore")
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()