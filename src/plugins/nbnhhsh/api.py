"""网络用语查询（nbnhhsh / 能不能好好说话）。

调用 lab.magiconch.com 的公开接口把拼音缩写翻译成可能的含义，
例如 "awmc" -> ["唉舞萌痴", "爱玩mc", ...]。

接口：POST https://lab.magiconch.com/api/nbnhhsh/guess
  请求体：{"text": "<缩写>"}
  响应： [{"name": "...", "trans": ["...", ...]}, ...]
  （text 可用逗号分隔多个词，会返回多个对象；无结果时 trans 可能缺失/null）

网络逻辑与 easter_egg/ai_match.py 保持一致：模块级 ClientSession 复用、
分段超时、ClientError 归类返回，便于调用方给出可区分原因的提示。
"""

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://lab.magiconch.com/api/nbnhhsh/guess"

REQUEST_TIMEOUT = 15
_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=10, sock_read=12)

_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://lab.magiconch.com",
    "referer": "https://lab.magiconch.com/nbnhhsh/",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ),
}

_session: aiohttp.ClientSession | None = None


def _build_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(limit=8, ttl_dns_cache=300)
    return aiohttp.ClientSession(timeout=_TIMEOUT, connector=connector)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = _build_session()
    return _session


async def guess(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """查询缩写含义。

    返回 (结果列表, 错误码)：
      - 成功：([{"name":..., "trans":[...]}, ...], None)
      - 失败：( [], "config" | "timeout" | "network" | "http_<状态码>" | "parse" | "unknown" )
    """
    session = await _get_session()
    try:
        async with session.post(API_URL, headers=_HEADERS, json={"text": text}) as response:
            if response.status != 200:
                logger.warning(f"nbnhhsh 接口返回 HTTP {response.status}")
                return [], f"http_{response.status}"
            try:
                data = await response.json(content_type=None)
            except Exception as e:  # noqa: BLE001 - 响应非 JSON 时归为 parse
                logger.warning(f"nbnhhsh 响应解析失败: {e}")
                return [], "parse"
    except aiohttp.ClientError as e:
        logger.warning(f"nbnhhsh 网络错误: {e}")
        return [], "network"
    except TimeoutError:
        logger.warning("nbnhhsh 请求超时")
        return [], "timeout"
    except Exception as e:  # noqa: BLE001 - 兜底，查询失败不应打崩处理流程
        logger.warning(f"nbnhhsh 未知错误: {e}")
        return [], "unknown"

    if not isinstance(data, list):
        return [], "parse"
    return data, None


def format_error(error: str) -> str:
    """把错误码翻译成用户可读的中文提示。"""
    if error == "timeout":
        return "查询超时，请稍后再试"
    if error == "network":
        return "网络异常，查询失败，请稍后再试"
    if error == "parse":
        return "接口返回异常，查询失败"
    if error.startswith("http_"):
        return f"接口返回错误（{error[5:]}），请稍后再试"
    if error == "config":
        return "查询服务配置异常"
    return "查询失败，请稍后再试"
