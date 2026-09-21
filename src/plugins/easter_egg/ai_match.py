import asyncio
import json
import logging
from pathlib import Path

import aiohttp
import nonebot

config = nonebot.get_driver().config

# 配置默认值
BASE_URL = getattr(config, "base_url", "")
API_KEY = getattr(config, "api_key", "")
MODEL_THINK = getattr(config, "model_think", "")  # 模糊匹配用
MODEL_CHAT = getattr(config, "model_chat", "")    # 对话回退用

# 对话模式自定义提示词文件（UTF-8），文件内可任意换行排版；
# 该文件属本地配置，不在版本库内（见 prompt_chat.example.md 模板与 .gitignore）。
# 文件缺失、无法读取或内容为空时「不附加任何提示词」：直接把用户在彩蛋后的原话交给模型。
CHAT_PROMPT_FILE = (
    Path(__file__).resolve().parent.parent.parent / "asserts" / "easter_egg" / "prompt_chat.md"
)

# 每个插件的 AI 并发上限：默认 5（可 AI_CONCURRENCY 覆盖），过高会冲击 API 链路、过低会排队拖慢。
try:
    AI_CONCURRENCY = max(1, int(getattr(config, "ai_concurrency", 5) or 5))
except (TypeError, ValueError):
    AI_CONCURRENCY = 5
AI_SEMAPHORE = asyncio.Semaphore(AI_CONCURRENCY)

# 分段时间配置（秒）：connect 为 TCP/TLS 建立连接阶段；sock_read 为两次收到数据的最大间隔
#（容忍大模型流式生成的停顿）；total 为整个请求总时长上限，可用 AI_TIMEOUT 覆盖（默认 180）。
try:
    REQUEST_TIMEOUT = max(1, int(getattr(config, "ai_timeout", 180) or 180))
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


def _load_chat_prompt() -> str:
    """加载对话模式系统提示词：优先独立文件。

    文件缺失、无法读取或内容为空时返回空串——对话回退将不携带任何系统提示词，
    等价于把用户在「彩蛋」后的原话直接交给模型。
    """
    try:
        text = CHAT_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.warning(f"彩蛋对话提示词文件 {CHAT_PROMPT_FILE} 无法读取（{e!r}），本次运行不附加系统提示词")
        return ""
    except UnicodeError as e:
        logger.warning(f"彩蛋对话提示词文件 {CHAT_PROMPT_FILE} 编码异常（{e!r}），本次运行不附加系统提示词")
        return ""
    if not text:
        logger.info(f"彩蛋对话提示词文件 {CHAT_PROMPT_FILE} 为空，本次运行不附加系统提示词")
        return ""
    return text


CHAT_SYSTEM_PROMPT = _load_chat_prompt()


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
    logger.warning("彩蛋 AI 配置缺失：BASE_URL 为空，AI 功能将不可用")
if not API_KEY:
    logger.warning("彩蛋 AI 配置缺失：API_KEY 为空，AI 功能将不可用")
if not MODEL_THINK:
    logger.warning("彩蛋 AI 配置缺失：MODEL_THINK 为空，彩蛋模糊匹配将不可用")
if not MODEL_CHAT:
    logger.warning("彩蛋 AI 配置缺失：MODEL_CHAT 为空，彩蛋对话回退将不可用")


async def _chat_completion(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int = 4500,
    temperature: float = 0.3,
) -> tuple[str | None, str | None]:
    """调用 OpenAI 兼容 /chat/completions，返回 (content, error)。

    content 为回复文本（成功时）；error 为 None 表示流程正常完成：
      - 成功且有内容 -> (content, None)
      - finish_reason 非 stop -> (None, None)（视为无内容但非错误）
    error 非 None 表示发生错误，值为机器可读原因标识：
      config / timeout / network / parse / http_<status> / unknown
    """
    # 配置不完整时快速失败，不发起请求
    if not BASE_URL or not API_KEY or not model:
        logger.error("AI 配置不完整，跳过请求（BASE_URL/API_KEY/model 存在空值）")
        return None, "config"

    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
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
                        logger.warning(f"AI API finish_reason={choice['finish_reason']!r}，视为无内容")
                        return None, None

                    return choice["message"]["content"].strip(), None
        except asyncio.TimeoutError:
            if attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI 请求超时（>{REQUEST_TIMEOUT}s），第 {attempt}/{AI_RETRY_ATTEMPTS} 次，等待 {AI_RETRY_BASE_DELAY * attempt:.0f}s 后重试")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI 请求超时（>{REQUEST_TIMEOUT}s）")
            return None, "timeout"
        except _HttpError as exc:
            if exc.status in TRANSIENT_HTTP_STATUS and attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI API 返回 HTTP {exc.status}（瞬时故障），第 {attempt}/{AI_RETRY_ATTEMPTS} 次，等待 {AI_RETRY_BASE_DELAY * attempt:.0f}s 后重试")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI API 返回 HTTP {exc.status}: {exc.body}")
            return None, f"http_{exc.status}"
        except aiohttp.ClientError as e:
            if attempt < AI_RETRY_ATTEMPTS:
                logger.warning(f"AI 网络错误（第 {attempt}/{AI_RETRY_ATTEMPTS} 次，将重试）: {e!r}")
                await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)
                continue
            logger.error(f"AI 网络错误: {e!r}")
            return None, "network"
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, aiohttp.ContentTypeError) as e:
            logger.error(f"AI 响应解析失败: {type(e).__name__}: {e}")
            return None, "parse"
        except Exception as e:
            logger.error(f"AI 未预期错误: {type(e).__name__}: {e}")
            return None, "unknown"

    return None, "unknown"  # 理论上不可达（所有分支均 return）


async def ai_match(message: str, keywords: dict[str, list[str]]) -> tuple[list[str], str | None]:
    """AI 模糊匹配彩蛋关键词，返回 (关键词列表, 错误原因)。

    返回的键一定真实存在于传入的 `keywords` 中：模型可能杜撰键名，或照抄提示词里的
    格式示例，这类键下游无法解析，会导致「AI 匹配到关键词但未找到可用图片」并跳过对话
    回退，因此这里统一过滤掉。

    错误原因为 None 表示流程正常完成（此时关键词列表可能为空，表示无匹配）；
    非 None 表示发生错误（config / timeout / network / parse / http_<status> / unknown）。
    """
    keywords_list = [f"{key}: {', '.join(aliases)}" for key, aliases in keywords.items()]
    keywords_info = "\n".join(keywords_list)

    system_prompt = f"""你是一个彩蛋关键词匹配助手。
任务：根据用户输入快速返回所有可能匹配的关键词（只返回关键词本身，不要返回任何别名），如果用户的输入与下列彩蛋主题（人物、AI 模型、学校、组织、梗等）毫无关系则直接返回NONE
方法：在第一次浏览关键词的过程中对每个关键词进行匹配，例如：'SomeKey: 别名甲, 别名乙 - 不相关，...'，不要思考太多，不需要重新检查，浏览过后直接输出结果。规则：用户的输入与关键词的任意一个别名相关即认为匹配，多个用逗号分隔，无匹配返回NONE
注意：只能返回下方列表中出现过的键名，禁止杜撰，也禁止返回列表以外的任何内容。

关键词及其别名的列表如下：
{keywords_info}"""

    result, error = await _chat_completion(
        MODEL_THINK,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=4500,
        temperature=0.3,
    )
    if error:
        return [], error
    if not result or result == "NONE":
        return [], None
    keys = [k.strip() for k in result.split(",") if k.strip()]
    # 只保留本次关键词表里真实存在的键，杜撰/示例残留的键一律丢弃（丢弃后为空即走对话回退）
    return [k for k in keys if k in keywords], None


async def ai_chat(user_text: str) -> tuple[str | None, str | None]:
    """彩蛋对话回退：把用户原文交给对话模型生成回复。

    若配置了系统提示词（prompt_chat.md 非空）则作为 system 消息一并发送；
    否则不携带任何系统提示词，直接询问模型。
    返回 (回复文本, 错误原因)。错误原因语义同 _chat_completion。
    """
    messages: list[dict] = []
    if CHAT_SYSTEM_PROMPT:
        messages.append({"role": "system", "content": CHAT_SYSTEM_PROMPT})
    messages.append({"role": "user", "content": user_text})
    result, error = await _chat_completion(
        MODEL_CHAT,
        messages,
        max_tokens=2000,
        temperature=0.8,
    )
    if error:
        return None, error
    return result, None
