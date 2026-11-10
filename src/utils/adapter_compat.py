"""跨适配器（OneBot v11 / QQ 官方）的图片与回复构造工具。

背景：
- 本项目同时跑 OneBot v11（NapCat/SnowLuma 私域协议）与 QQ 官方机器人（开放平台）。
- 两者的 Message / MessageSegment 互不兼容：把 v11 的 image 段交给 qq 的 Bot.send
  会直接抛错，反之亦然。
- 官方群消息**一条只能携带一个媒体**（adapter 内部 `_extract_qq_media` 只取 image[-1]），
  多图必须拆条；而官方被动回复有「5 分钟 / 每条消息最多 5 条」的硬限制
  （超出报 40034128），因此官方侧统一收敛为「1 条文本 + 最多 1 张图」。
- 官方「全量消息模式」下，content 里的 @ 会被替换成 `<@member_openid>` / `<@all>`，
  命令解析前需要剥掉。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Message as V11Message
from nonebot.adapters.onebot.v11 import MessageSegment as V11Segment
from nonebot.adapters.qq import Message as QQMessage
from nonebot.adapters.qq import MessageSegment as QQSegment
from nonebot.adapters.qq.event import QQMessageEvent

# 官方被动回复上限（每条用户消息最多回 5 条），留一条余量给错误提示
MAX_QQ_REPLIES = 5

# 全量模式下 content 里的 @ 占位符
QQ_MENTION_RE = re.compile(r"<@[^>\s]{0,64}>")


def is_qq_event(event: Event) -> bool:
    """是否为 QQ 官方适配器的事件。"""
    return isinstance(event, QQMessageEvent)


def image_segment(event: Event, path: Path) -> Any:
    """按事件所属适配器生成图片消息段。"""
    if is_qq_event(event):
        return QQSegment.file_image(path)
    return V11Segment.image(path)


def build_message(event: Event, segments: list[Any]):
    """用事件所属适配器的 Message 类包装消息段。"""
    if is_qq_event(event):
        return QQMessage(segments)
    return V11Message(segments)


def compose_image_reply(
    event: Event,
    images: list[tuple[str, Path]],
    header: str = "",
    footer: str = "",
):
    """构造「文本 + 图片」回复。

    images 为 [(展示名, 路径), ...]。
    - v11：图片全部发出，保持原有观感。
    - 官方：只发第一张，其余用一行文字列出（一条消息只能带一个媒体）。
    """
    seg = QQSegment if is_qq_event(event) else V11Segment
    parts: list[Any] = []
    if header:
        parts.append(seg.text(header))

    if is_qq_event(event):
        shown, hidden = images[:1], images[1:]
    else:
        shown, hidden = images, []

    for label, path in shown:
        parts.append(seg.text(f"{label}: "))
        parts.append(image_segment(event, path))

    if hidden:
        names = "、".join(label for label, _ in hidden)
        parts.append(
            seg.text(f"\n另有 {len(hidden)} 个匹配（{names}），请逐个查询。")
        )

    if footer:
        parts.append(seg.text(footer))

    return build_message(event, parts)


def strip_qq_mentions(event: Event) -> None:
    """剥掉全量模式下 content 中的 `<@openid>` / `<@all>` 占位符。

    官方 @ 模式下 content 本身不含 @，此函数是 no-op。
    """
    if not is_qq_event(event):
        return
    try:
        message = event.get_message()
    except ValueError:
        return

    changed = False
    for segment in message:
        if segment.type != "text":
            continue
        raw = segment.data.get("text", "")
        cleaned = QQ_MENTION_RE.sub("", raw).lstrip()
        if cleaned != raw:
            segment.data["text"] = cleaned
            changed = True

    if changed:
        try:
            event.message = message  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - 模型不允许赋值时放弃，不影响主流程
            pass
