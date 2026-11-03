"""审批调用封装：OneBot v11 set_group_add_request。

与事件分发解耦：接收 action（approve/reject）+ 参数，负责 dry_run 与异常处理。
注意 NoneBot 的 OneBot v11 Bot 通过 __getattr__ 动态转发 API，
所以 bot.set_group_add_request(...) 实际调用的是 call_api("set_group_add_request")。
"""

from __future__ import annotations

import logging
from typing import Any

from nonebot.adapters.onebot.v11.exception import ActionFailed, NetworkError

from .verify_core import REASON_INVALID_CODE

logger = logging.getLogger(__name__)


async def apply_decision(
    bot: Any,
    *,
    flag: str,
    group_id: int,
    user_id: int | str,
    action: str,
    reason: str | None,
    dry_run: bool,
) -> bool:
    """执行（或在 dry_run 下只记录）审批。

    返回 True 表示真的调用了 set_group_add_request；dry_run/无需审批时返回 False。
    """
    if action not in ("approve", "reject"):
        return False

    approve = action == "approve"
    # OneBot 要求 reason 是字符串；同意时留空
    reason_text = "" if approve else (reason or REASON_INVALID_CODE)

    if dry_run:
        logger.info(
            "[dry-run] 将执行 set_group_add_request | 群%s user=%s flag=…%s approve=%s reason=%r",
            group_id,
            user_id,
            flag[-8:] if len(flag) > 8 else flag,
            approve,
            reason_text,
        )
        return False

    try:
        await bot.set_group_add_request(
            flag=flag,
            sub_type="add",
            approve=approve,
            reason=reason_text,
        )
    except ActionFailed as exc:
        info = getattr(exc, "info", None) or {}
        logger.error(
            "set_group_add_request 失败 | 群%s user=%s approve=%s retcode=%s %s",
            group_id,
            user_id,
            approve,
            info.get("retcode", "?"),
            str(info.get("message") or info.get("wording") or "")[:200],
        )
        return False
    except NetworkError as exc:
        logger.error("set_group_add_request 网络异常 | 群%s user=%s: %s", group_id, user_id, exc)
        return False

    logger.info("set_group_add_request 完成 | 群%s user=%s approve=%s", group_id, user_id, approve)
    return True
