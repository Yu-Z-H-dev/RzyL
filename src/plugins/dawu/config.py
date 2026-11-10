import json
from pathlib import Path

import nonebot

from .keywords import KEYWORDS

config = nonebot.get_driver().config


def _parse_groups(raw) -> list[int]:
    """解析群号配置，兼容 str / int / list 三种形态。

    NoneBot 加载自定义配置时会先尝试 json.loads，导致：
      - 单个群号（如 123456）被解析成 int
      - JSON 数组（如 [123456, 654321]）被解析成 list
      - 逗号分隔多个群号（如 123456,654321）保持 str
    这里统一做类型归一，避免群组筛选失效。
    """
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, list):
        return [int(x) for x in raw if str(x).strip().isdigit()]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        if isinstance(parsed, list):
            return [int(x) for x in parsed if str(x).strip().isdigit()]
        if isinstance(parsed, int):
            return [parsed]
        return [int(x) for x in str(parsed).split(",") if x.strip().isdigit()]
    return []


def _parse_openids(raw) -> list[str]:
    """解析官方机器人的 group_openid 白名单（字符串，不能按数字过滤）。"""
    if raw is None:
        return []
    parsed = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = text
    if isinstance(parsed, (list, tuple)):
        return [str(x).strip() for x in parsed if str(x).strip()]
    return [item.strip() for item in str(parsed).split(",") if item.strip()]


# 允许使用本插件的群聊列表，留空表示所有群聊都可以使用
ALLOWED_GROUPS = _parse_groups(getattr(config, 'dawu_allowed_groups', None))

# 官方机器人（QQ 开放平台）的群 group_openid 白名单，留空表示所有群都放行。
# 注意：openid 是按机器人加密的，同一个群在不同机器人下值不同，需从日志收集。
QQ_ALLOWED_GROUPS = _parse_openids(getattr(config, 'dawu_qq_allowed_groups', None))


def get_image_path(keyword: str) -> Path:
    return Path.cwd() / "src" / "asserts" / "dawu" / f"{keyword}.jpg"
