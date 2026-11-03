"""入群申请自动审核的纯逻辑层。

本模块**只依赖标准库**：不导入 aiohttp / nonebot，也不做任何网络或文件 IO。
留言解析、页面解析、QQ 与学号校验全是纯函数，可直接单测
（见 tests/test_group_verify.py，它按文件路径单独加载本模块）。

分工：
  - 网络抓取   -> proof_client.py
  - 名单核验   -> namelist.py（本模块只依赖它提供的 exists / match_prefix 两个方法）
  - 流程编排   -> service.py
  - 审批调用   -> approval.py
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol

# ---------------------------------------------------------------------------
# 常量与用户可见文案
# ---------------------------------------------------------------------------

# 证明码：站点生成的是数字串，实测既有 6 位也有 10 位
CODE_MIN_LEN = 6
CODE_MAX_LEN = 10

# 站点允许申请者「选择展示几位学号」，其余位数以掩码字符替代
MASK_CHARS = "*＊·•…"

REASON_FORMAT = "留言格式不符，请按「答案：<证明码>」填写"
REASON_INVALID_CODE = "证明码无效或已过期"
REASON_QQ_MISMATCH = "QQ号与证明码不匹配"
REASON_STUDENT_INVALID = "学号格式不合法"
REASON_STUDENT_MASKED = "请在 qq.ustc.life 生成证明码时选择显示完整学号，然后重新提交申请"
REASON_STUDENT_UNVERIFIED = "学号未通过名单核验"
REASON_NAMELIST_UNAVAILABLE = "学号名单不可用，转人工核对"

# 「答案：」后面必须是纯数字；先抓整段数字再校验长度，
# 这样 12 位之类的异常输入不会被截成合法长度蒙混过关。
_ANSWER_RE = re.compile(r"答案\s*[:：]\s*(\d+)")

# 页面字段：宽松匹配，不依赖标签结构与 CSS。
# 页面文本已去标签、压缩空白并做 NFKC 归一（全角标点/数字变半角）。
_PROOF_CODE_RE = re.compile(r"证明码\s*[:：]\s*(\d{4,})")
_STUDENT_RE = re.compile(
    r"学号\s*(?:[（(]\s*或\s*教工号\s*[)）])?\s*[:：]\s*([A-Za-z]{0,4}\d[\w*]*)"
)
_QQ_RE = re.compile(r"QQ\s*号\s*[:：]\s*(\d{5,})")

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProofInfo:
    """从证明页解析出的三项信息。"""

    code: str
    student_id: str
    qq: str
    excerpt: str = ""

    def masked(self) -> "ProofInfo":
        """脱敏副本：学号与 QQ 只保留首尾，用于 INFO 日志。"""
        return ProofInfo(
            code=self.code,
            student_id=mask_student_id(self.student_id),
            qq=mask_qq(self.qq),
            excerpt=self.excerpt,
        )


@dataclass(frozen=True)
class Verdict:
    """审核结论。action: approve / reject / manual。"""

    action: Literal["approve", "reject", "manual"]
    reason: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class FetchResult:
    """证明页抓取结果（纯数据，便于纯函数层与测试共用）。

    status: ok=拿到页面 / not_found=HTTP 404·410 / unavailable=服务不可用
    """

    status: Literal["ok", "not_found", "unavailable"]
    html: str | None = None
    error: str | None = None


class NamelistLookup(Protocol):
    """名单核验接口（namelist.StudentIdIndex 实现）。"""

    def exists(self, student_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------


def mask_student_id(student_id: str) -> str:
    """PB25061270 -> PB25****70；长度不足时退化处理。"""
    sid = (student_id or "").strip()
    if len(sid) <= 6:
        return sid[:2] + "*" * max(0, len(sid) - 2)
    return f"{sid[:4]}****{sid[-2:]}"


def mask_qq(qq: str) -> str:
    """2135251032 -> 2135****32。"""
    q = (qq or "").strip()
    if len(q) <= 6:
        return q[:2] + "*" * max(0, len(q) - 2)
    return f"{q[:4]}****{q[-2:]}"


# ---------------------------------------------------------------------------
# 留言解析
# ---------------------------------------------------------------------------


def extract_answer_code(comment: str) -> str | None:
    """从「…答案：3843650398」里提取证明码。

    兼容中英文冒号、全角数字与多余空白；取不到、位数不在 6~10 之间、
    或答案部分不是纯数字，一律返回 None（调用方据此直接拒绝，不发请求）。
    """
    if not comment:
        return None
    text = unicodedata.normalize("NFKC", comment)
    match = _ANSWER_RE.search(text)
    if not match:
        return None
    code = match.group(1)
    if not (CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN):
        return None
    return code


# ---------------------------------------------------------------------------
# 页面解析
# ---------------------------------------------------------------------------


def html_to_text(html: str) -> str:
    """把 HTML 压成一行纯文本，供正则宽松匹配。

    去掉 script/style 与所有标签、还原实体、NFKC 归一全角字符、
    压缩空白。这样站点改用 div/p/span 或加属性都不会影响解析。
    """
    if not html:
        return ""
    import html as html_lib

    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip()


def parse_proof_html(html: str) -> ProofInfo | None:
    """从证明页解析出（证明码, 学号, QQ 号）。

    三项缺一即返回 None —— 站点对「不存在/已过期的证明码」返回的是
    首页模板（HTTP 200）而不是 404，所以判据只能是字段缺失。
    """
    text = html_to_text(html)
    if not text:
        return None

    code_m = _PROOF_CODE_RE.search(text)
    student_m = _STUDENT_RE.search(text)
    qq_m = _QQ_RE.search(text)
    if not code_m or not student_m or not qq_m:
        return None

    start = max(0, code_m.start() - 40)
    excerpt = text[start : code_m.end() + 160]
    return ProofInfo(
        code=code_m.group(1),
        student_id=student_m.group(1).strip(),
        qq=qq_m.group(1).strip(),
        excerpt=excerpt,
    )


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None


def split_masked_student_id(student_id: str) -> tuple[str, bool]:
    """拆分掩码学号，返回 (可见前缀, 是否为掩码)。"""
    sid = (student_id or "").strip()
    masked = any(ch in MASK_CHARS for ch in sid)
    if not masked:
        return sid, False
    prefix = re.split("[" + re.escape(MASK_CHARS) + "]", sid, maxsplit=1)[0].strip()
    return prefix, True


def verify_proof(
    *,
    proof: ProofInfo | None,
    user_id: int | str,
    student_id_pattern: str = r"^PB\d{8}$",
    namelist: NamelistLookup | None = None,
    require_namelist: bool = True,
    require_full_student_id: bool = True,
    expected_code: str | None = None,
) -> Verdict:
    """三重校验：页面 QQ 必须等于申请者 QQ；学号必须完整；学号必须在名单里。

    - 掩码学号（站点允许只显示前几位）一律不放行：要求完整学号才可能与名单**精确**比对。
      require_full_student_id=True → 直接拒（理由告诉申请人怎么改）；
      False → 转人工（无法自动核验，但不误拒）。
    - require_namelist=True 且名单不可用 → 转人工（不再退化成「只按正则放行」）。
    """
    if proof is None:
        return Verdict("reject", REASON_INVALID_CODE, "页面无有效信息")

    if expected_code and proof.code != expected_code:
        return Verdict(
            "reject",
            REASON_INVALID_CODE,
            f"页面证明码 {proof.code} 与留言证明码 {expected_code} 不一致",
        )

    user_id_str = str(user_id).strip()
    if proof.qq.strip() != user_id_str:
        return Verdict(
            "reject",
            REASON_QQ_MISMATCH,
            f"页面 QQ {mask_qq(proof.qq)} != 申请者 {mask_qq(user_id_str)}",
        )

    pattern = _compile(student_id_pattern)
    if pattern is None:
        return Verdict(
            "manual",
            None,
            f"配置项 student_id_pattern 非法：{student_id_pattern!r}",
        )

    student_id, masked = split_masked_student_id(proof.student_id)
    if masked:
        detail = f"页面学号被掩码：{proof.student_id!r}（可见前缀 {student_id!r}），无法与名单精确比对"
        if require_full_student_id:
            return Verdict("reject", REASON_STUDENT_MASKED, detail)
        return Verdict("manual", None, detail)

    if not pattern.fullmatch(proof.student_id):
        return Verdict(
            "reject",
            REASON_STUDENT_INVALID,
            f"学号不匹配 {student_id_pattern}：{mask_student_id(proof.student_id)}",
        )

    if require_namelist:
        if namelist is None:
            return Verdict(
                "manual",
                None,
                f"名单不可用，无法核验学号 {mask_student_id(proof.student_id)}",
            )
        if not namelist.exists(proof.student_id):
            return Verdict(
                "reject",
                REASON_STUDENT_UNVERIFIED,
                f"学号 {mask_student_id(proof.student_id)} 不在名单内（非 24–26 届或名单缺人）",
            )

    return Verdict("approve", None, f"学号核验通过：{mask_student_id(proof.student_id)}")


def build_reject_reason(verdict: Verdict) -> str:
    """拒绝时返回给申请人的简短中文原因（同意时为空串）。"""
    if verdict.action != "reject":
        return ""
    return verdict.reason or REASON_INVALID_CODE
