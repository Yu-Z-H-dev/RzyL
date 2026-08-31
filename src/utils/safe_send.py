"""发送容错工具。

背景：NapCat/QQ 的 sendMsg 在 QQ 侧限频或网络抖动时会间歇性超时
（NoneBot 表现为 ActionFailed, retcode=1200, "Timeout: NTEvent ... sendMsg"），
且失败的消息可能已被服务端延迟写入成功（EventRet.result=0），因此
**只吞异常、不重试**（重试会造成重复消息）。

鉴于此前的实现把 send/finish 直接写在命令处理流程里，一条 "正在思考..."
发送失败会连带中断后续 AI 匹配与最终回复。本模块提供 safe_send /
safe_finish，失败时记录 warning 日志并返回 False，交由调用方决定后续逻辑。
"""

import logging
from typing import Any

from nonebot.adapters.onebot.v11.exception import ActionFailed, NetworkError
from nonebot.exception import FinishedException, StopPropagation

logger = logging.getLogger(__name__)


def _log_send_failure(exc: BaseException) -> None:
    """把发送失败原因压缩成一条 warning 日志。"""
    if isinstance(exc, ActionFailed):
        info = getattr(exc, "info", None) or {}
        retcode = info.get("retcode", "?")
        wording = str(info.get("message") or info.get("wording") or "").strip().replace("\n", " ")
        logger.warning(f"消息发送失败 (retcode={retcode}): {wording[:200]}")
    else:
        logger.warning(f"消息发送异常 ({type(exc).__name__}): {exc}")


async def safe_send(matcher: Any, message: Any, **kwargs: Any) -> bool:
    """发送一条消息，失败时吞掉异常并返回 False（不中断调用方流程）。

    正常返回 True。FinishedException / StopPropagation 属于流程控制异常，
    原样上抛，不做处理。
    """
    try:
        await matcher.send(message, **kwargs)
    except (ActionFailed, NetworkError) as exc:
        _log_send_failure(exc)
        return False
    except (FinishedException, StopPropagation):
        raise
    except Exception as exc:  # noqa: BLE001 - 兜底，发送失败不应打崩处理流程
        _log_send_failure(exc)
        return False
    return True


async def safe_finish(matcher: Any, message: Any = None, **kwargs: Any) -> bool:
    """发送一条消息并结束当前处理；发送失败时吞掉异常并返回 False。

    finish 正常路径会抛出 FinishedException / StopPropagation（流程控制），
    这里捕获后视为成功返回 True，保证调用方控制流不变。
    """
    try:
        await matcher.finish(message, **kwargs)
    except (ActionFailed, NetworkError) as exc:
        _log_send_failure(exc)
        return False
    except (FinishedException, StopPropagation):
        return True
    except Exception as exc:  # noqa: BLE001 - 兜底，发送失败不应打崩处理流程
        _log_send_failure(exc)
        return False
    return True
