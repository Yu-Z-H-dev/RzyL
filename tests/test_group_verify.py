"""group_verify 纯逻辑与编排的单测（标准库 unittest，零新增依赖）。

运行：
    cd ~/RzyL && .venv/bin/python -m unittest discover -s tests -v

注意：本文件**不导入** src/plugins/group_verify/__init__.py（那里会注册 NoneBot
matcher，需要先 nonebot.init()）。这里用一个空的合成包名把目录挂进 sys.path，
直接加载 verify_core / service / rate_limit / namelist —— 它们都只依赖标准库。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "src" / "plugins" / "group_verify"
ALIAS = "gv_under_test"

if ALIAS not in sys.modules:
    _pkg = types.ModuleType(ALIAS)
    _pkg.__path__ = [str(PKG_DIR)]  # type: ignore[attr-defined]
    sys.modules[ALIAS] = _pkg


def _load(name: str):
    return importlib.import_module(f"{ALIAS}.{name}")


core = _load("verify_core")
service = _load("service")
rate_limit = _load("rate_limit")
namelist_mod = _load("namelist")

FetchResult = core.FetchResult
Settings = service.Settings
verify_proof = core.verify_proof
parse_proof_html = core.parse_proof_html
extract_answer_code = core.extract_answer_code
ProofInfo = core.ProofInfo

GROUP = 1105450795
QQ = "2135251032"
SID = "PB25061270"
CODE = "3843650398"

# 真实页面的关键片段（2026-11-02 从 https://qq.ustc.life/p/3843650398/ 抓取）
REAL_PAGE = """<!DOCTYPE html><html><body><div class="container">
<h1><a href="https://qq.ustc.life/">USTC QQ 号证明</a></h1><hr>
<div style="font-size: 1.5em">
    <p>证明码：3843650398</p>
    <p>学号（或教工号）：PB25061270</p>
    <p>QQ 号：2135251032</p>
</div>
<p>注意：本网站只验证学号（或教工号），不验证用户填写的 QQ 号。</p>
<strong>如何生成证明？</strong>
<ol><li>……选择你希望展示几位学号（或教工号）……</li></ol>
</div></body></html>"""

# 无效/过期证明码时站点实际返回的首页模板（HTTP 200，没有任何证明字段）
INDEX_PAGE = """<!DOCTYPE html><html><body><div class="container">
<h1><a href="https://qq.ustc.life/">USTC QQ 号证明</a></h1><hr>
<form class="form-inline"><input id="code" type="tel" placeholder="证明码">
<button type="submit">查看</button></form>
<p>本网站只验证学号（或教工号），不验证用户填写的 QQ 号。</p>
</div></body></html>"""


class FakeIndex:
    """名单核验接口的内存实现。"""

    def __init__(self, ids: list[str]) -> None:
        self.ids = set(ids)

    def exists(self, student_id: str) -> bool:
        return student_id in self.ids


class FakeNamelist:
    def __init__(self, index) -> None:
        self.index = index

    async def get(self):
        return self.index


def make_proof(**kwargs) -> ProofInfo:
    data = {"code": CODE, "student_id": SID, "qq": QQ, "excerpt": "…"}
    data.update(kwargs)
    return ProofInfo(**data)


def make_settings(**kwargs) -> Settings:
    data = {
        "enabled": True,
        "group_whitelist": frozenset({GROUP}),
        "dry_run": True,
        "min_request_interval_seconds": 0.0,
        "queue_max_size": 10,
        "queue_wait_seconds": 5.0,
        "flag_ttl_seconds": 600.0,
        "student_id_pattern": r"^PB\d{8}$",
        "request_timeout_seconds": 10.0,
        "proof_url_template": "https://qq.ustc.life/p/{code}/",
        "require_namelist": True,
        "require_full_student_id": True,
    }
    data.update(kwargs)
    return Settings(**data)


class ExtractAnswerCodeTest(unittest.TestCase):
    def test_real_comment(self):
        comment = "留言: 问题：qq.ustc.life网站验证 答案：3843650398"
        self.assertEqual(extract_answer_code(comment), "3843650398")

    def test_ten_digit_and_six_digit(self):
        self.assertEqual(extract_answer_code("答案:123456"), "123456")
        self.assertEqual(extract_answer_code("答案：3843650398"), "3843650398")

    def test_fullwidth_and_extra_space(self):
        self.assertEqual(extract_answer_code("答案 ：　３８４３６５０３９８"), "3843650398")

    def test_missing_answer(self):
        for text in ("", "问题：qq.ustc.life网站验证", "答案：", "留言：想进群"):
            self.assertIsNone(extract_answer_code(text), text)

    def test_wrong_length(self):
        self.assertIsNone(extract_answer_code("答案：12345"))  # 5 位太短
        self.assertIsNone(extract_answer_code("答案：384365039812"))  # 12 位太长

    def test_non_digit(self):
        self.assertIsNone(extract_answer_code("答案：abcd1234"))


class ParseProofHtmlTest(unittest.TestCase):
    def test_real_page(self):
        proof = parse_proof_html(REAL_PAGE)
        assert proof is not None
        self.assertEqual(proof.code, CODE)
        self.assertEqual(proof.student_id, SID)
        self.assertEqual(proof.qq, QQ)

    def test_index_page_has_no_fields(self):
        # 站点对不存在/过期证明码返回首页模板（200），必须判为解析失败
        self.assertIsNone(parse_proof_html(INDEX_PAGE))

    def test_structure_changed_still_parses(self):
        # 结构变动：换标签、加属性、全角冒号、字段顺序变化
        html = (
            "<table><tr><td><span class='k'>证明码:</span><b>3843650398</b></td></tr></table>"
            "<div><em>学号 (或教工号)：</em><i>PB25061270</i></div>"
            "<section data-x=1><p>QQ号:2135251032</p></section>"
        )
        proof = parse_proof_html(html)
        assert proof is not None
        self.assertEqual((proof.code, proof.student_id, proof.qq), (CODE, SID, QQ))

    def test_missing_any_field_fails(self):
        broken = REAL_PAGE.replace("<p>QQ 号：2135251032</p>", "")
        self.assertIsNone(parse_proof_html(broken))

    def test_empty_html(self):
        self.assertIsNone(parse_proof_html(""))


class VerifyProofTest(unittest.TestCase):
    def setUp(self):
        self.index = FakeIndex([SID, "PB24000001"])

    def verify(self, **kwargs):
        params = {
            "proof": make_proof(),
            "user_id": int(QQ),  # 事件里 user_id 是 int，必须能比较
            "student_id_pattern": r"^PB\d{8}$",
            "namelist": self.index,
        }
        params.update(kwargs)
        return verify_proof(**params)

    def test_approve_happy_path(self):
        verdict = self.verify()
        self.assertEqual(verdict.action, "approve")
        self.assertIsNone(verdict.reason)

    def test_int_and_str_user_id_both_ok(self):
        self.assertEqual(self.verify(user_id=int(QQ)).action, "approve")
        self.assertEqual(self.verify(user_id=QQ).action, "approve")

    def test_qq_mismatch(self):
        verdict = self.verify(proof=make_proof(qq="2135251033"))
        self.assertEqual(verdict.action, "reject")
        self.assertEqual(verdict.reason, core.REASON_QQ_MISMATCH)

    def test_student_id_pattern_invalid(self):
        for sid in ("PB2506127", "PB250612700", "SA25061270", "PBABCDEFGH"):
            verdict = self.verify(proof=make_proof(student_id=sid))
            self.assertEqual(verdict.action, "reject", sid)
            self.assertEqual(verdict.reason, core.REASON_STUDENT_INVALID, sid)

    def test_student_id_not_in_namelist(self):
        verdict = self.verify(proof=make_proof(student_id="PB25999999"))
        self.assertEqual(verdict.action, "reject")
        self.assertEqual(verdict.reason, core.REASON_STUDENT_UNVERIFIED)

    def test_namelist_optional_when_require_disabled(self):
        verdict = self.verify(proof=make_proof(student_id="PB25999999"), require_namelist=False)
        self.assertEqual(verdict.action, "approve")

    def test_masked_student_id_is_rejected(self):
        # 要求完整学号：站点允许只展示前几位，出现掩码一律拒，并告知怎么改
        for masked in ("PB2506****", "PB2506**••", "PB2506＊****", "PB25******"):
            verdict = self.verify(proof=make_proof(student_id=masked))
            self.assertEqual(verdict.action, "reject", masked)
            self.assertEqual(verdict.reason, core.REASON_STUDENT_MASKED, masked)

    def test_masked_goes_manual_when_full_id_not_required(self):
        verdict = self.verify(
            proof=make_proof(student_id="PB2506****"), require_full_student_id=False
        )
        self.assertEqual(verdict.action, "manual")

    def test_namelist_unavailable_goes_manual(self):
        verdict = self.verify(namelist=None)
        self.assertEqual(verdict.action, "manual")
        self.assertIsNone(verdict.reason)

    def test_student_id_outside_cohorts(self):
        # 名单只收 24–26 届；21 届学号格式合法但查不到 -> 拒
        verdict = self.verify(proof=make_proof(student_id="PB21000001"))
        self.assertEqual(verdict.action, "reject")
        self.assertEqual(verdict.reason, core.REASON_STUDENT_UNVERIFIED)

    def test_proof_none(self):
        verdict = self.verify(proof=None)
        self.assertEqual(verdict.action, "reject")
        self.assertEqual(verdict.reason, core.REASON_INVALID_CODE)

    def test_expected_code_mismatch(self):
        verdict = self.verify(expected_code="111111")
        self.assertEqual(verdict.action, "reject")
        self.assertEqual(verdict.reason, core.REASON_INVALID_CODE)

    def test_bad_pattern_goes_manual(self):
        verdict = self.verify(student_id_pattern="([")
        self.assertEqual(verdict.action, "manual")


class MaskTest(unittest.TestCase):
    def test_masks(self):
        self.assertEqual(core.mask_student_id(SID), "PB25****70")
        self.assertEqual(core.mask_qq(QQ), "2135****32")


class IntervalLimiterTest(unittest.IsolatedAsyncioTestCase):
    async def test_min_interval_between_requests(self):
        limiter = rate_limit.IntervalLimiter(0.1, queue_max_size=5, wait_timeout=5)
        stamps = []
        for _ in range(3):
            self.assertTrue(await limiter.acquire())
            stamps.append(time.monotonic())
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        for gap in gaps:
            self.assertGreaterEqual(gap, 0.09)  # 允许 10ms 调度误差

    async def test_queue_full_returns_false(self):
        limiter = rate_limit.IntervalLimiter(0.0, queue_max_size=1, wait_timeout=1)
        limiter._waiting = 1  # 模拟已有请求在排队
        self.assertFalse(await limiter.acquire())
        self.assertEqual(limiter.waiting, 1)

    async def test_wait_timeout_returns_false(self):
        limiter = rate_limit.IntervalLimiter(5.0, queue_max_size=5, wait_timeout=0.05)
        self.assertTrue(await limiter.acquire())  # 立刻拿到第一个槽位
        limiter._next_allowed = time.monotonic() + 5.0  # 下一个必须等 5s，超时转人工
        limiter.wait_timeout = 0.05
        self.assertFalse(await limiter.acquire())


class FlagCacheTest(unittest.TestCase):
    def test_dedup_and_empty(self):
        cache = rate_limit.FlagCache(ttl_seconds=600)
        self.assertTrue(cache.first_seen("flag-a"))
        self.assertFalse(cache.first_seen("flag-a"))
        self.assertTrue(cache.first_seen("flag-b"))
        self.assertFalse(cache.first_seen(""))

    def test_ttl_expiry(self):
        cache = rate_limit.FlagCache(ttl_seconds=10)
        now = [1000.0]
        cache.clock = lambda: now[0]
        self.assertTrue(cache.first_seen("f"))
        now[0] += 5
        self.assertFalse(cache.first_seen("f"))
        now[0] += 11
        self.assertTrue(cache.first_seen("f"))


class StudentIndexTest(unittest.TestCase):
    def test_build_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            path.write_text(
                json.dumps(
                    {
                        "PB25061270": {"name": "张三", "grade": "2025"},
                        "PB24000001": {"name": "李四", "grade": "2024"},
                        "PB26000001": {"name": "王五", "grade": "2026"},
                        "PB21000001": {"name": "老学长", "grade": "2021"},  # 届别不在白名单
                        "00008": {"name": "工号"},  # 非 PB 键
                    }
                ),
                encoding="utf-8",
            )
            index = namelist_mod._build_index(path, (2024, 2025, 2026))
            assert index is not None
            self.assertEqual(len(index), 3)
            self.assertTrue(index.exists("PB25061270"))
            self.assertFalse(index.exists("PB21000001"))
            self.assertFalse(index.exists("PB25999999"))

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = namelist_mod._build_index(Path(tmp) / "nope.json", (2025,))
            self.assertIsNone(index)

    def test_lazy_index(self):
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "identity.json"
                path.write_text(json.dumps({"PB25061270": {}}), encoding="utf-8")
                lazy = namelist_mod.LazyStudentIndex(path, (2025,))
                index = await lazy.get()
                assert index is not None
                self.assertTrue(index.exists("PB25061270"))
                self.assertTrue(lazy.loaded)

        asyncio.run(run())


class ProcessApplicationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.index = FakeIndex([SID])
        self.namelist = FakeNamelist(self.index)
        self.limiter = rate_limit.IntervalLimiter(0.0, queue_max_size=10, wait_timeout=5)
        self.flags = rate_limit.FlagCache()
        self.calls: list[str] = []

    async def fake_fetch(self, code, *, url_template, timeout_seconds):
        self.calls.append(code)
        return FetchResult("ok", html=REAL_PAGE)

    async def run_service(self, *, comment=None, fetch=None, settings=None, **_):
        return await service.process_application(
            group_id=GROUP,
            user_id=int(QQ),
            flag="flag-xyz",
            comment=comment if comment is not None else "问题：qq.ustc.life网站验证 答案：3843650398",
            settings=settings or make_settings(),
            limiter=self.limiter,
            flag_cache=self.flags,
            namelist=self.namelist,
            fetch=fetch or self.fake_fetch,
        )

    async def test_approve_flow(self):
        outcome = await self.run_service()
        self.assertEqual(outcome.action, "approve")
        self.assertEqual(outcome.code, CODE)
        self.assertEqual(self.calls, [CODE])

    async def test_disabled_is_ignored_without_fetch(self):
        outcome = await self.run_service(settings=make_settings(enabled=False))
        self.assertEqual(outcome.action, "ignored")
        self.assertEqual(self.calls, [])

    async def test_group_not_in_whitelist_is_ignored(self):
        outcome = await self.run_service(settings=make_settings(group_whitelist=frozenset({1})))
        self.assertEqual(outcome.action, "ignored")
        self.assertEqual(self.calls, [])

    async def test_duplicate_flag_is_ignored(self):
        first = await self.run_service()
        second = await self.run_service()
        self.assertEqual(first.action, "approve")
        self.assertEqual(second.action, "ignored")
        self.assertEqual(len(self.calls), 1)

    async def test_format_error_rejects_without_fetch(self):
        outcome = await self.run_service(comment="问题：我想进群")
        self.assertEqual(outcome.action, "reject")
        self.assertEqual(outcome.reason, core.REASON_FORMAT)
        self.assertEqual(self.calls, [])

    async def test_page_without_fields_is_invalid_code(self):
        async def index_fetch(code, *, url_template, timeout_seconds):
            return FetchResult("ok", html=INDEX_PAGE)

        outcome = await self.run_service(fetch=index_fetch)
        self.assertEqual(outcome.action, "reject")
        self.assertEqual(outcome.reason, core.REASON_INVALID_CODE)

    async def test_http_404_is_invalid_code(self):
        async def not_found(code, *, url_template, timeout_seconds):
            return FetchResult("not_found", error="http_404")

        outcome = await self.run_service(fetch=not_found)
        self.assertEqual(outcome.action, "reject")
        self.assertEqual(outcome.reason, core.REASON_INVALID_CODE)

    async def test_service_unavailable_retries_once_then_manual(self):
        attempts = []

        async def down(code, *, url_template, timeout_seconds):
            attempts.append(code)
            return FetchResult("unavailable", error="http_502")

        outcome = await self.run_service(fetch=down)
        self.assertEqual(outcome.action, "manual")
        self.assertEqual(len(attempts), 2)  # 初次 + 1 次重试，绝不多试

    async def test_retry_success_after_transient_failure(self):
        attempts = []

        async def flaky(code, *, url_template, timeout_seconds):
            attempts.append(code)
            if len(attempts) == 1:
                return FetchResult("unavailable", error="timeout")
            return FetchResult("ok", html=REAL_PAGE)

        outcome = await self.run_service(fetch=flaky)
        self.assertEqual(outcome.action, "approve")
        self.assertEqual(len(attempts), 2)

    async def test_queue_full_goes_manual(self):
        self.limiter._waiting = self.limiter.queue_max_size
        outcome = await self.run_service()
        self.assertEqual(outcome.action, "manual")
        self.assertEqual(self.calls, [])

    async def test_qq_mismatch_rejects(self):
        async def other_qq(code, *, url_template, timeout_seconds):
            return FetchResult("ok", html=REAL_PAGE.replace(QQ, "9999999999"))

        outcome = await self.run_service(fetch=other_qq)
        self.assertEqual(outcome.action, "reject")
        self.assertEqual(outcome.reason, core.REASON_QQ_MISMATCH)

    async def test_masked_student_rejected(self):
        async def masked(code, *, url_template, timeout_seconds):
            return FetchResult("ok", html=REAL_PAGE.replace(SID, "PB2506****"))

        outcome = await self.run_service(fetch=masked)
        self.assertEqual(outcome.action, "reject")
        self.assertEqual(outcome.reason, core.REASON_STUDENT_MASKED)

    async def test_namelist_unavailable_goes_manual(self):
        self.namelist = FakeNamelist(None)  # 名单文件缺失/损坏
        outcome = await self.run_service()
        self.assertEqual(outcome.action, "manual")


if __name__ == "__main__":
    unittest.main()
