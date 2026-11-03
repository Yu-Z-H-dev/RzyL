"""qq.ustc.life 证明码页面抓取。

只做「一次 HTTP GET + 归类结果」，不做重试（重试由 service.py 负责，
因为重试也必须重新走限流队列）。风格与 nbnhhsh/api.py、ai_match.py 一致：
模块级 ClientSession 复用 + 分段超时 + 字符串错误码。
"""

from __future__ import annotations

import logging

import aiohttp
import nonebot

from .verify_core import FetchResult

logger = logging.getLogger(__name__)

# 常规浏览器 UA：该站没有反爬，但没有 UA 的裸请求不礼貌也易被前置代理挡
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

DEFAULT_URL_TEMPLATE = "https://qq.ustc.life/p/{code}/"
DEFAULT_TIMEOUT = 10.0

_sessions: dict[float, aiohttp.ClientSession] = {}


def _build_session(total: float) -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(
        total=total, connect=min(5.0, total), sock_read=total
    )
    connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=300)
    return aiohttp.ClientSession(timeout=timeout, connector=connector)


async def _get_session(total: float) -> aiohttp.ClientSession:
    session = _sessions.get(total)
    if session is None or session.closed:
        session = _build_session(total)
        _sessions[total] = session
    return session


async def _close_sessions() -> None:
    for key, session in list(_sessions.items()):
        if not session.closed:
            await session.close()
        _sessions.pop(key, None)


nonebot.get_driver().on_shutdown(_close_sessions)


async def fetch_proof(
    code: str,
    *,
    url_template: str = DEFAULT_URL_TEMPLATE,
    timeout_seconds: float = DEFAULT_TIMEOUT,
) -> FetchResult:
    """GET 证明页，按 HTTP 语义归类。

    注意：该站对「不存在/已过期」的证明码返回的是首页模板（HTTP 200），
    所以这里的 not_found 只管 HTTP 404/410；「页面里没有有效信息」
    由 parse_proof_html 判定（见 service.py）。
    """
    url = url_template.format(code=code)
    session = await _get_session(timeout_seconds)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status == 200:
                return FetchResult("ok", html=await response.text())
            if response.status in (404, 410):
                logger.info("证明码 %s 对应的页面不存在（HTTP %d）", code, response.status)
                return FetchResult("not_found", error=f"http_{response.status}")
            body = (await response.text())[:120].replace("\n", " ")
            logger.warning("证明码页面返回 HTTP %d: %s", response.status, body)
            return FetchResult("unavailable", error=f"http_{response.status}")
    except TimeoutError:
        logger.warning("证明码页面请求超时（>%.0fs）", timeout_seconds)
        return FetchResult("unavailable", error="timeout")
    except aiohttp.ClientError as exc:
        logger.warning("证明码页面网络错误：%s: %s", type(exc).__name__, exc)
        return FetchResult("unavailable", error="network")
    except Exception as exc:  # noqa: BLE001 - 抓取失败一律按服务不可用处理，不误伤真实申请人
        logger.warning("证明码页面未知错误：%s: %s", type(exc).__name__, exc)
        return FetchResult("unavailable", error="unknown")
