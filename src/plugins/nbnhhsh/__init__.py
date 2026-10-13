"""解释 —— 网络用语（拼音缩写）查询。

用法：解释 <缩写>
例如：解释 awmc   ->   1. 唉舞萌痴  2. 爱玩mc  ...
数据来自 lab.magiconch.com 的 nbnhhsh 公开接口。

仅 `JIESHI_ALLOWED_GROUPS` 列出的群聊可用本命令（留空 = 所有群都可用）。
未列出的群里本命令**完全不响应**（静默）；私聊不受限制。
"""

import json
import logging
from typing import Any

from nonebot import get_driver, require
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


def _parse_groups(raw: Any) -> list[int]:
    """解析群号配置，兼容 str / int / list 三种形态（与 dawu/config.py 同一套逻辑）。

    NoneBot 加载自定义配置时会先尝试 json.loads，导致单个群号变 int、
    JSON 数组变 list，这里统一归一。
    """
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, list):
        return [int(x) for x in raw if str(x).strip().isdigit()]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        if isinstance(parsed, list):
            return [int(x) for x in parsed if str(x).strip().isdigit()]
        if isinstance(parsed, int):
            return [parsed]
        return [int(x) for x in str(parsed).split(",") if x.strip().isdigit()]
    return []


# 允许使用本命令的群聊（白名单），留空 = 所有群都可用；私聊永不受限
ALLOWED_GROUPS: list[int] = _parse_groups(
    getattr(get_driver().config, "jieshi_allowed_groups", None)
)


def in_allowed_group(event: MessageEvent) -> bool:
    """Rule：消息所在群在白名单中时放行。

    私聊（无 group_id）放行；白名单为空时所有群放行；
    否则仅当群号在 ALLOWED_GROUPS 中时放行。
    """
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return True
    if not ALLOWED_GROUPS:
        return True
    return int(group_id) in ALLOWED_GROUPS


def validate_input(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > MAX_INPUT_LEN:
        return False
    return True


jieShi = on_alconna(
    Alconna("解释", Args["text", str]),
    rule=Rule(in_allowed_group),
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
