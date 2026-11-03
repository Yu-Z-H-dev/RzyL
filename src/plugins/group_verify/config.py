r"""group_verify 插件配置。

NoneBot 的 config 是 pydantic-settings（extra="allow"），所以任意大写环境变量
都能通过 `getattr(config, "小写名", 默认)` 读到 —— 与 dawu2/config.py、
nbnhhsh/__init__.py 里读 DAWU2_ALLOWED_GROUPS / JIESHI_ALLOWED_GROUPS 的做法一致。

环境变量（写在 .env.secret 或 .env）：
  GROUP_VERIFY_ENABLED                     总开关，默认 false
  GROUP_VERIFY_GROUP_WHITELIST             群号白名单，逗号分隔（留空=哪个群都不处理）
  GROUP_VERIFY_DRY_RUN                     默认 true：只记录将执行的审批，不真调用
  GROUP_VERIFY_MIN_REQUEST_INTERVAL_SECONDS 默认 1
  GROUP_VERIFY_QUEUE_MAX_SIZE              默认 10
  GROUP_VERIFY_QUEUE_WAIT_SECONDS          默认 30（排队超时即转人工）
  GROUP_VERIFY_STUDENT_ID_PATTERN          默认 ^PB\d{8}$
  GROUP_VERIFY_REQUEST_TIMEOUT_SECONDS     默认 10
  GROUP_VERIFY_PROOF_URL_TEMPLATE          默认 https://qq.ustc.life/p/{code}/
  GROUP_VERIFY_FLAG_TTL_SECONDS            默认 600（flag 幂等窗口）
  GROUP_VERIFY_REQUIRE_FULL_STUDENT_ID     默认 true（页面学号必须是完整学号，掩码一律拒绝）
  GROUP_VERIFY_REQUIRE_NAMELIST            默认 true（全码学号也要能在名单里找到）
  GROUP_VERIFY_NAMELIST_PATH               默认 ~/ustc_bot/GetNameList/data/final/identity.json
  GROUP_VERIFY_NAMELIST_COHORTS            默认 2024,2025,2026
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import nonebot

from .service import Settings

logger = logging.getLogger(__name__)

DEFAULT_STUDENT_ID_PATTERN = r"^PB\d{8}$"
DEFAULT_PROOF_URL_TEMPLATE = "https://qq.ustc.life/p/{code}/"
DEFAULT_NAMELIST_PATH = str(
    Path.home() / "ustc_bot" / "GetNameList" / "data" / "final" / "identity.json"
)
DEFAULT_NAMELIST_COHORTS = (2024, 2025, 2026)

_config = nonebot.get_driver().config


def _parse_groups(raw: Any) -> frozenset[int]:
    """解析群号配置，兼容 str / int / list 三种形态。

    NoneBot 加载自定义配置时会先尝试 json.loads，导致单个群号变 int、
    JSON 数组变 list，这里统一归一（与 dawu2/config.py 同一套逻辑）。
    """
    if raw is None:
        return frozenset()
    if isinstance(raw, int):
        return frozenset({raw})
    if isinstance(raw, list):
        return frozenset(int(x) for x in raw if str(x).strip().isdigit())
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return frozenset()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        if isinstance(parsed, list):
            return frozenset(int(x) for x in parsed if str(x).strip().isdigit())
        if isinstance(parsed, int):
            return frozenset({parsed})
        return frozenset(int(x) for x in str(parsed).split(",") if x.strip().isdigit())
    return frozenset()


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on", "y", "t"}


def _parse_float(raw: Any, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _parse_int(raw: Any, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _parse_cohorts(raw: Any) -> tuple[int, ...]:
    if raw is None:
        return DEFAULT_NAMELIST_COHORTS
    items = raw if isinstance(raw, (list, tuple)) else str(raw).replace("，", ",").split(",")
    years = sorted({int(x) for x in items if str(x).strip().isdigit()})
    return tuple(years) or DEFAULT_NAMELIST_COHORTS


def _parse_pattern(raw: Any) -> str:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return DEFAULT_STUDENT_ID_PATTERN
    try:
        re.compile(text)
    except re.error as exc:
        logger.error("GROUP_VERIFY_STUDENT_ID_PATTERN 非法（%s），回退默认 %s", exc, DEFAULT_STUDENT_ID_PATTERN)
        return DEFAULT_STUDENT_ID_PATTERN
    return text


def _build_settings() -> Settings:
    settings = Settings(
        enabled=_parse_bool(getattr(_config, "group_verify_enabled", None), False),
        group_whitelist=_parse_groups(getattr(_config, "group_verify_group_whitelist", None)),
        dry_run=_parse_bool(getattr(_config, "group_verify_dry_run", None), True),
        min_request_interval_seconds=_parse_float(
            getattr(_config, "group_verify_min_request_interval_seconds", None), 1.0
        ),
        queue_max_size=_parse_int(getattr(_config, "group_verify_queue_max_size", None), 10),
        queue_wait_seconds=_parse_float(
            getattr(_config, "group_verify_queue_wait_seconds", None), 30.0, minimum=1.0
        ),
        flag_ttl_seconds=_parse_float(
            getattr(_config, "group_verify_flag_ttl_seconds", None), 600.0, minimum=1.0
        ),
        student_id_pattern=_parse_pattern(
            getattr(_config, "group_verify_student_id_pattern", None)
        ),
        request_timeout_seconds=_parse_float(
            getattr(_config, "group_verify_request_timeout_seconds", None), 10.0, minimum=1.0
        ),
        proof_url_template=str(
            getattr(_config, "group_verify_proof_url_template", None)
            or DEFAULT_PROOF_URL_TEMPLATE
        ),
        require_namelist=_parse_bool(getattr(_config, "group_verify_require_namelist", None), True),
        require_full_student_id=_parse_bool(
            getattr(_config, "group_verify_require_full_student_id", None), True
        ),
    )

    if settings.enabled and not settings.group_whitelist:
        logger.warning(
            "group_verify 已启用，但 GROUP_VERIFY_GROUP_WHITELIST 为空 —— 任何群的申请都不会被处理"
        )
    logger.info(
        "group_verify 配置：enabled=%s dry_run=%s 群白名单=%s 间隔=%.1fs 队列=%d 学号正则=%s 要求完整学号=%s 名单核验=%s",
        settings.enabled,
        settings.dry_run,
        sorted(settings.group_whitelist) or "空",
        settings.min_request_interval_seconds,
        settings.queue_max_size,
        settings.student_id_pattern,
        settings.require_full_student_id,
        settings.require_namelist,
    )
    return settings


SETTINGS = _build_settings()

# 名单路径/届别单独放出来，供 LazyStudentIndex 使用（不属于 Settings）
NAMELIST_PATH = str(getattr(_config, "group_verify_namelist_path", None) or DEFAULT_NAMELIST_PATH).strip()
NAMELIST_COHORTS = _parse_cohorts(getattr(_config, "group_verify_namelist_cohorts", None))
