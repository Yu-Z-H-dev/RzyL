import asyncio
import json
import logging

import aiohttp
import nonebot

from .keywords import KEYWORDS

config = nonebot.get_driver().config

# 配置默认值
BASE_URL = getattr(config, 'base_url', "")
API_KEY = getattr(config, 'api_key', "")
MODEL_THINK = getattr(config, 'model_think', "")

url = f"{BASE_URL}/chat/completions"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 每个插件的 AI 并发上限：默认 5（可 AI_CONCURRENCY 覆盖），过高会冲击 API 链路、过低会排队拖慢。
try:
    AI_CONCURRENCY = max(1, int(getattr(config, 'ai_concurrency', 5) or 5))
except (TypeError, ValueError):
    AI_CONCURRENCY = 5
AI_SEMAPHORE = asyncio.Semaphore(AI_CONCURRENCY)

# 分段时间配置（秒）：connect 为 TCP/TLS 建立连接阶段；sock_read 为两次读取之间的最大间隔
#（容忍大模型流式生成的停顿）；total 为整个请求总时长上限，可用 AI_TIMEOUT 覆盖（默认 180）。
try:
    REQUEST_TIMEOUT = max(1, int(getattr(config, 'ai_timeout', 180) or 180))
except (TypeError, ValueError):
    REQUEST_TIMEOUT = 180
_AI_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=30, sock_read=120)

logger = logging.getLogger(__name__)

# —— 瞬时故障重试：上游网关偶发 503 / 连接重置 / 超时，重试通常可立即恢复 ——
TRANSIENT_HTTP_STATUS = {500, 502, 503, 504, 529}
AI_RETRY_ATTEMPTS = 2  # 最多尝试 2 次（初次 + 1 次重试）
AI_RETRY_BASE_DELAY = 1.0  # 重试退避基础时长（秒），第 n 次失败后等待 n 秒


class _HttpError(Exception):
    """AI API 返回非 200 状态码。"""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body

# 复用的长连接会话：每个请求不再重复 TCP/TLS 握手，是缓解 AI 超时/变慢的关键之一。
_session: aiohttp.ClientSession | None = None


def _build_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(limit=AI_CONCURRENCY, ttl_dns_cache=300)
    return aiohttp.ClientSession(timeout=_AI_TIMEOUT, connector=connector)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = _build_session()
    return _session


async def _close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


# 退出时关闭连接池，避免资源泄漏与告警
nonebot.get_driver().on_shutdown(_close_session)

# 启动期配置校验：配置缺失尽早暴露，而不是每次查询失败才报
if not BASE_URL:
    logger.warning("AI 匹配配置缺失：BASE_URL 为空，AI 模糊匹配将不可用")
if not API_KEY:
    logger.warning("AI 匹配配置缺失：API_KEY 为空，AI 模糊匹配将不可用")
if not MODEL_THINK:
    logger.warning("AI 匹配配置缺失：MODEL_THINK 为空，AI 模糊匹配将不可用")


async def ai_match(message: str, keywords: dict[str, list[str]]) -> tuple[list[str], str | None]:
    """AI 模糊匹配，返回 (关键词列表, 错误原因)。

    错误原因为 None 表示流程正常完成（此时关键词列表可能为空，表示无匹配）；
    非 None 表示发生错误，值为机器可读原因标识：
      config / timeout / network / parse / http_<status> / unknown
    """
    # 配置不完整时快速失败，不发起请求
    if not BASE_URL or not API_KEY or not MODEL_THINK:
        logger.error("AI 匹配配置不完整，跳过请求（BASE_URL/API_KEY/MODEL_THINK 存在空值）")
        return [], "config"

    keywords_list = []
    for keyword, aliases in keywords.items():
        aliases_str = ", ".join(aliases)
        keywords_list.append(f"{keyword}: {aliases_str}")

    keywords_info = "\n".join(keywords_list)

    system_prompt = f"""你是一个关键词匹配助手。
任务：根据用户输入快速返回所有可能匹配的英文关键词，不要返回任何别名，如果用户的输入与物理实验毫无关系则直接返回NONE
方法：在第一次浏览关键词的过程中对每个关键词进行匹配，例如：'Introduction_and_Simple_Pendulum: 绪论, 单摆 - 不相关，...'，不要思考太多，不需要重新检查，浏览过后直接输出结果。规则：用户的输入与关键词的任意一个别名相关即认为匹配，多个用逗号分隔，无匹配返回NONE

关键词及其别名的列表如下：
{keywords_info}"""

    data = {
        "model": MODEL_THINK,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        "max_tokens": 4500,
        "temperature": 0.3
    }

    for attempt in range(1, AI_RETRY_ATTEMPTS + 1):
        try:
            async with AI_SEMAPHORE:
                session = await _get_session()
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status != 200:
                        body = (await response.text())[:200]
                        raise _HttpError(response.status, body)

                    response_json = await response.json()
                    choice = response_json["choices"][0]

                    if choice["finish_reason"] != "stop":
                        logger.warning(f"AI 匹配 finish_reason={choice['finish_reason']!r}，视为无匹配")
                        return [], None

                    result = choice["message"]["content"].strip()
        except asyncio.TimeoutError:
            if attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI 匹配请求超时（>{REQUEST_TIMEOUT}s），第 {attempt}/{AI_RETRY_ATTEMPTS} 次，等待 {AI_RETRY_BASE_DELAY * attempt:.0f}s 后重试")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI 匹配请求超时（>{REQUEST_TIMEOUT}s）")
            return [], "timeout"
        except _HttpError as exc:
            if exc.status in TRANSIENT_HTTP_STATUS and attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI 匹配 API 返回 HTTP {exc.status}（瞬时故障），第 {attempt}/{AI_RETRY_ATTEMPTS} 次，等待 {AI_RETRY_BASE_DELAY * attempt:.0f}s 后重试")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI 匹配 API 返回 HTTP {exc.status}: {exc.body}")
            return [], f"http_{exc.status}"
        except aiohttp.ClientError as e:
            if attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI 匹配网络错误（第 {attempt}/{AI_RETRY_ATTEMPTS} 次，将重试）: {e!r}")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI 匹配网络错误: {e!r}")
            return [], "network"
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, aiohttp.ContentTypeError) as e:
            logger.error(f"AI 匹配响应解析失败: {type(e).__name__}: {e}")
            return [], "parse"
        except Exception as e:
            logger.error(f"AI 匹配未预期错误: {type(e).__name__}: {e}")
            return [], "unknown"

    return [], "unknown"  # 理论上不可达（所有分支均 return）

    if result == "NONE":
        return [], None

    keywords_found = [k.strip() for k in result.split(",")]
    return keywords_found, None
