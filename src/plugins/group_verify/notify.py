"""转人工通知（最小实现：结构化 WARN 日志）。

没有现成的管理通知通道，所以先把「需要人来看一眼」的申请落一条
结构化 WARN 日志；等有通道了只改这一个函数即可，调用点不用动。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_manual_review(
    *,
    group_id: int,
    user_id: int | str,
    flag: str,
    comment: str,
    reason: str,
) -> None:
    """记录一条待人工审核的申请。

    TODO: 接入通知通道后改为私聊管理员，例如：
        await bot.send_private_msg(user_id=<管理员QQ>, message=f"待审核入群申请 …")
    现在只落日志，不引入任何新依赖/新消息通道。
    """
    logger.warning(
        "待人工审核 | 群=%s user=%s flag=…%s 原因=%s 留言=%r",
        group_id,
        user_id,
        flag[-8:] if len(flag) > 8 else flag,
        reason,
        (comment or "")[:200],
    )
