"""入群申请自动验证（qq.ustc.life 证明码）。

事件来源：NapCat 会把事件**广播**给所有正向 WS 客户端，本插件所在的 NoneBot
进程（连 ws://127.0.0.1:3001）本来就能收到 GroupRequestEvent，不需要新建连接、
不需要动 NapCat/MaiBot。

本文件只做三件事：过滤事件 → 调 service.process_application → 按结论审批。
判定逻辑全在 verify_core（纯函数）；网络在 proof_client；审批在 approval。

⚠️ 日志可见性：NoneBot 只把自己的 loguru 接到输出，插件里 stdlib logging 的 INFO
默认会被丢弃（只有 WARNING+ 靠 logging.lastResort 到 stderr）。本项目在 `bot.py`
顶部显式 `logging.basicConfig(level=logging.INFO, …)` 才让这里的 INFO（审核结论、
dry-run 预告）可见 —— 删掉那行，dry_run 观察期就什么都看不到。
"""

from __future__ import annotations

import logging

from nonebot import on_request
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent
from nonebot.rule import Rule

from .approval import apply_decision
from .config import NAMELIST_COHORTS, NAMELIST_PATH, SETTINGS
from .namelist import LazyStudentIndex
from .notify import notify_manual_review
from .rate_limit import FlagCache, IntervalLimiter
from .service import process_application
from .verify_core import mask_student_id, mask_qq

logger = logging.getLogger(__name__)

# 进程内单例：限流器保证对 qq.ustc.life 的请求间隔；flag 去重防事件重放
LIMITER = IntervalLimiter(
    SETTINGS.min_request_interval_seconds,
    SETTINGS.queue_max_size,
    SETTINGS.queue_wait_seconds,
)
FLAG_CACHE = FlagCache(SETTINGS.flag_ttl_seconds)
NAMELIST = LazyStudentIndex(NAMELIST_PATH, NAMELIST_COHORTS)


def _is_group_add_request(event: GroupRequestEvent) -> bool:
    """只要群入群申请（加群），其它 request（好友申请/邀请入群）一概不管。

    注意用 getattr 取值：这个规则会对**所有** request 事件求值，
    而 FriendRequestEvent 没有 sub_type 字段，直接取属性会抛 AttributeError。
    """
    return (
        str(getattr(event, "post_type", "")) == "request"
        and str(getattr(event, "request_type", "")) == "group"
        and str(getattr(event, "sub_type", "")) == "add"
    )


verify = on_request(rule=Rule(_is_group_add_request), priority=10, block=True)


@verify.handle()
async def _handle(bot: Bot, event: GroupRequestEvent) -> None:
    outcome = await process_application(
        group_id=event.group_id,
        user_id=event.user_id,
        flag=event.flag,
        comment=event.comment or "",
        settings=SETTINGS,
        limiter=LIMITER,
        flag_cache=FLAG_CACHE,
        namelist=NAMELIST,
    )

    if not outcome.handled:
        # 非白名单群 / 总开关关闭 / 重复 flag：静默（只留 DEBUG）
        logger.debug(
            "入群申请忽略 | 群%s user=%s 原因=%s", event.group_id, event.user_id, outcome.detail
        )
        return

    logger.info(
        "入群申请 | 群%s user=%s 证明码=%s 学号=%s 动作=%s 说明=%s",
        event.group_id,
        event.user_id,
        outcome.code or "-",
        mask_student_id(outcome.proof.student_id) if outcome.proof else "-",
        outcome.action,
        outcome.detail,
    )
    if logger.isEnabledFor(logging.DEBUG) and outcome.proof is not None:
        # DEBUG 才出完整值；INFO 只出掩码
        logger.debug(
            "入群申请详情 | 页面学号=%s 页面QQ=%s 页面片段=%r",
            outcome.proof.student_id,
            mask_qq(outcome.proof.qq),
            outcome.proof.excerpt[:200],
        )

    if outcome.action == "manual":
        notify_manual_review(
            group_id=event.group_id,
            user_id=event.user_id,
            flag=event.flag,
            comment=event.comment or "",
            reason=outcome.detail,
        )
        return

    await apply_decision(
        bot,
        flag=event.flag,
        group_id=event.group_id,
        user_id=event.user_id,
        action=outcome.action,
        reason=outcome.reason,
        dry_run=SETTINGS.dry_run,
    )
