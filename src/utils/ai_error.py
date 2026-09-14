"""AI 调用失败原因 → 可区分的用户提示。

背景：ai_match / ai_chat 返回的是机器可读错误码
（config / timeout / network / parse / http_<status> / unknown），
但各插件上层过去把除 config 外的所有失败都显示成同一句
"AI 匹配服务暂时不可用"，导致用户无法区分到底是：

  - AI 确实没匹配到（这其实不是错误：error 为 None 且关键词为空）
  - 网络连不通 / 请求超时
  - 上游网关返回 5xx
  - 响应解析失败

排查时只能翻服务器日志。本模块把错误码翻译成能区分原因的中文提示。

注意：**"AI 成功但无匹配"不属于错误**（error 为 None），
上层应走"没有找到匹配的关键词"分支，不要用本模块。
"""

# 错误码 → 用户提示
_AI_ERROR_MESSAGES: dict[str, str] = {
    "config": "AI 服务未配置，请联系管理员",
    "timeout": "AI 响应超时（上游繁忙），请稍后再试",
    "network": "无法连接 AI 服务（网络异常），请稍后再试",
    "parse": "AI 返回内容无法解析，请稍后再试",
    "unknown": "AI 服务出现未知错误，请稍后再试",
}


def format_ai_error(error: str) -> str:
    """把 ai_match / ai_chat 的错误码翻译成可区分原因的用户提示。

    http_<status> 会展开成具体状态码，便于判断是上游 503 还是别的；
    未知错误码则原样附在提示里，避免新错误码被静默吞掉。
    """
    if error.startswith("http_"):
        return f"AI 服务返回 HTTP {error[5:]}，请稍后再试"
    return _AI_ERROR_MESSAGES.get(error, f"AI 服务异常（{error}），请稍后再试")
