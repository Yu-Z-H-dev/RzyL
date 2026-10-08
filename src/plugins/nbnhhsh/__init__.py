"""解释 —— 网络用语（拼音缩写）查询。

用法：解释 <缩写>
例如：解释 awmc   ->   1. 唉舞萌痴  2. 爱玩mc  ...
数据来自 lab.magiconch.com 的 nbnhhsh 公开接口。
"""

import logging

from nonebot import require
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule

from .api import format_error, guess

logger = logging.getLogger(__name__)

require("nonebot_plugin_alconna")

from src.utils.safe_send import safe_finish  # noqa: E402

from nonebot_plugin_alconna import (  # noqa: E402
    Alconna,
    Args,
    Match,
    on_alconna,
)

# 单条消息最多展示的解释条数（避免刷屏）
MAX_TRANS = 20
# 输入长度上限
MAX_INPUT_LEN = 50


def validate_input(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > MAX_INPUT_LEN:
        return False
    return True


jieShi = on_alconna(
    Alconna("解释", Args["text", str]),
    priority=0,
    block=True,
)


@jieShi.handle()
async def _(
    event: MessageEvent,
    text: Match[str],
):
    if not text.available:
        return

    query = text.result.strip()
    if not validate_input(query):
        await safe_finish(jieShi, f"请输入要查询的内容（1-{MAX_INPUT_LEN} 个字符）")
        return

    logger.info(f"收到解释请求: 群{getattr(event, 'group_id', '私聊')}, 用户{event.user_id}, 内容{query}")

    results, error = await guess(query)
    if error:
        await safe_finish(jieShi, format_error(error), reply_message=True)
        return

    # 汇总所有 trans（接口可能返回多个同名对象）
    lines: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or query)
        trans = item.get("trans")
        if not trans or not isinstance(trans, list):
            continue
        # 去重但保留顺序
        seen: set[str] = set()
        uniq = []
        for t in trans:
            t = str(t).strip()
            if t and t not in seen:
                seen.add(t)
                uniq.append(t)
        if not uniq:
            continue
        lines.append(name)
        for i, t in enumerate(uniq[:MAX_TRANS], 1):
            lines.append(f"{i}. {t}")

    if not lines:
        await safe_finish(jieShi, f"「{query}」未查询到", reply_message=True)
        return

    await safe_finish(jieShi, "\n".join(lines), reply_message=True)
