"""审核编排：把「纯逻辑 + 限流 + 抓取」串成一次完整处理。

不依赖 nonebot / aiohttp 的具体实例：fetch 与 limiter 都是注入的，
因此 tests/test_group_verify.py 可以用假 fetch 覆盖全部分支。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .namelist import LazyStudentIndex
from .rate_limit import FlagCache, IntervalLimiter
from .verify_core import (
    REASON_FORMAT,
    REASON_INVALID_CODE,
    REASON_STUDENT_UNVERIFIED,
    FetchResult,
    ProofInfo,
    Verdict,
    extract_answer_code,
    mask_student_id,
    parse_proof_html,
    verify_proof,
)

logger = logging.getLogger(__name__)

FetchFn = Callable[..., Awaitable[FetchResult]]


@dataclass(frozen=True)
class Settings:
    """插件运行参数（由 config.py 从 NoneBot 配置构造）。"""

    enabled: bool = False
    group_whitelist: frozenset[int] = frozenset()
    dry_run: bool = True
    min_request_interval_seconds: float = 1.0
    queue_max_size: int = 10
    queue_wait_seconds: float = 30.0
    flag_ttl_seconds: float = 600.0
    student_id_pattern: str = r"^PB\d{8}$"
    request_timeout_seconds: float = 10.0
    proof_url_template: str = "https://qq.ustc.life/p/{code}/"
    require_namelist: bool = True
    require_full_student_id: bool = True


@dataclass(frozen=True)
class Outcome:
    """一次申请的处理结论。action: approve / reject / manual / ignored。"""

    action: Literal["approve", "reject", "manual", "ignored"]
    reason: str | None = None
    code: str | None = None
    proof: ProofInfo | None = None
    detail: str = ""

    @property
    def handled(self) -> bool:
        return self.action != "ignored"


async def process_application(
    *,
    group_id: int,
    user_id: int | str,
    flag: str,
    comment: str,
    settings: Settings,
    limiter: IntervalLimiter,
    flag_cache: FlagCache,
    namelist: LazyStudentIndex,
    fetch: FetchFn = None,  # type: ignore[assignment]
) -> Outcome:
    """处理一条入群申请，返回结论（不执行审批，审批在 approval.py）。"""
    if fetch is None:
        from .proof_client import fetch_proof

        fetch = fetch_proof

    # 1) 过滤：总开关 / 群白名单 / flag 去重
    if not settings.enabled:
        return Outcome("ignored", detail="总开关关闭")
    if int(group_id) not in settings.group_whitelist:
        return Outcome("ignored", detail=f"群 {group_id} 不在白名单")
    if not flag_cache.first_seen(flag):
        logger.info("入群申请 | 群%s flag=%s 重复事件，跳过", group_id, _tail(flag))
        return Outcome("ignored", detail="flag 已处理过（幂等去重）")

    # 2) 留言解析：失败直接拒绝，不发任何请求
    code = extract_answer_code(comment)
    if code is None:
        return Outcome(
            "reject",
            reason=REASON_FORMAT,
            detail=f"留言未匹配「答案：<证明码>」或位数不在 6~10：{comment[:80]!r}",
        )

    # 3) 抓取（限流 -> 一次请求；服务不可用时最多重试一次，且重试同样走队列）
    result = await _fetch_with_limits(code, settings, limiter, fetch)
    if result is None:
        return Outcome(
            "manual",
            code=code,
            detail="限流队列已满/排队超时，未发送请求",
        )
    if result.status == "unavailable":
        logger.warning("证明码 %s 首次抓取不可用（%s），重试一次（重新排队）", code, result.error)
        result = await _fetch_with_limits(code, settings, limiter, fetch)
        if result is None:
            return Outcome(
                "manual",
                code=code,
                detail="限流队列已满/排队超时，重试未能发出",
            )
        if result.status == "unavailable":
            return Outcome(
                "manual",
                code=code,
                detail=f"审核服务不可用（{result.error}），转人工",
            )

    # 4) 解析页面：404 或字段缺失都视为「证明码无效或已过期」
    if result.status == "not_found":
        return Outcome("reject", reason=REASON_INVALID_CODE, code=code, detail="HTTP 404/410")
    proof = parse_proof_html(result.html or "")
    if proof is None:
        return Outcome(
            "reject",
            reason=REASON_INVALID_CODE,
            code=code,
            detail="页面无有效信息（多为过期/不存在的证明码）",
        )

    # 5) 三重校验（QQ 严格相等 + 学号完整 + 学号在名单内）
    index = await namelist.get()
    verdict: Verdict = verify_proof(
        proof=proof,
        user_id=user_id,
        student_id_pattern=settings.student_id_pattern,
        namelist=index,
        require_namelist=settings.require_namelist,
        require_full_student_id=settings.require_full_student_id,
        expected_code=code,
    )
    if verdict.action == "reject" and verdict.reason == REASON_STUDENT_UNVERIFIED:
        # 名单缺人时留痕：事后可人工补名单/复核（学号只记掩码）
        logger.warning(
            "学号未在名单内 | 群%s user=%s 学号=%s 证明码=%s",
            group_id,
            user_id,
            mask_student_id(proof.student_id),
            code,
        )
    return Outcome(
        verdict.action,
        reason=verdict.reason,
        code=code,
        proof=proof,
        detail=verdict.detail,
    )


async def _fetch_with_limits(
    code: str,
    settings: Settings,
    limiter: IntervalLimiter,
    fetch: FetchFn,
) -> FetchResult | None:
    """排队拿槽位后抓取一次；拿不到槽位返回 None（调用方转人工）。"""
    if not await limiter.acquire():
        return None
    return await fetch(
        code,
        url_template=settings.proof_url_template,
        timeout_seconds=settings.request_timeout_seconds,
    )


def _tail(flag: str) -> str:
    """日志里只露 flag 尾部（flag 是审批用的凭据，不宜整条打进日志）。"""
    return f"…{flag[-8:]}" if len(flag) > 8 else flag
