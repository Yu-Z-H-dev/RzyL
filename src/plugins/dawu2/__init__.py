import logging
import time
from collections import defaultdict

from nonebot import require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, MessageSegment, Message
from nonebot.rule import Rule

from .ai_match import ai_match
from .config import ALLOWED_GROUPS, KEYWORDS, get_image_path

logger = logging.getLogger(__name__)

require("nonebot_plugin_alconna")
require("src.plugins.easter_egg")

from src.plugins.easter_egg import try_load_random_text
from src.utils.ai_error import format_ai_error
from src.utils.safe_send import safe_finish, safe_send

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Match,
    on_alconna,
)

RATE_LIMIT = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 10


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    user_requests = RATE_LIMIT[user_id]
    user_requests = [t for t in user_requests if now - t < 60]
    RATE_LIMIT[user_id] = user_requests
    return len(user_requests) < MAX_REQUESTS_PER_MINUTE


def validate_input(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > 100:
        return False
    return True


def check_group(event: MessageEvent) -> bool:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return True
    if not ALLOWED_GROUPS:
        return True
    return group_id in ALLOWED_GROUPS


dawu2 = on_alconna(
    Alconna("大雾2", Args["name", str]),
    rule=Rule(check_group),
    priority=0,
    block=True,
)


def find_keywords(text: str) -> list[str]:
    found_keywords = []
    for keyword, aliases in KEYWORDS.items():
        for alias in aliases:
            if alias in text:
                found_keywords.append(keyword)
                break
    return found_keywords


async def send_keyword_images(keywords: list[str], prefix: str = ""):
    messages = []
    missing_keywords = []
    for keyword in keywords:
        if keyword in KEYWORDS:
            image_path = get_image_path(keyword)
            if image_path.exists():
                first_alias = KEYWORDS[keyword][0] if KEYWORDS[keyword] else keyword
                messages.append(f"{prefix}{first_alias}:")
                messages.append(MessageSegment.image(image_path))
            else:
                missing_keywords.append(keyword)

    if messages:
        if missing_keywords:
            messages.append(
                f"{prefix}: {', '.join(keywords)}，但部分图片文件不存在: {', '.join(missing_keywords)}"
            )
        if random_text := try_load_random_text():
            messages.append(random_text)
        await safe_finish(dawu2, Message(messages))
    else:
        await safe_finish(dawu2, f"{prefix}: {', '.join(keywords)}，但所有图片文件都不存在")


@dawu2.handle()
async def _(
    event: MessageEvent,
    name: Match[str]
):
    logger.info(f"收到请求: 群{getattr(event, 'group_id', '私聊')}, 用户{event.user_id}, 内容{name.result}")

    if not name.available:
        return

    if not validate_input(name.result):
        await safe_finish(dawu2, "输入无效，请提供有效的实验名称（1-100个字符）")
        return

    if not check_rate_limit(event.user_id):
        await safe_finish(dawu2, "请求过于频繁，请稍后再试（每分钟最多10次请求）")
        return

    if name.result == "ls":
        output_lines = []
        for keyword, aliases in KEYWORDS.items():
            output_lines.append(", ".join(aliases))
        await safe_finish(dawu2, "\n".join(output_lines))
    elif name.result == "help":
        await safe_finish(dawu2,
            "使用方法: 大雾2 实验名称\n例如: 大雾2 霍尔效应\n\n这是二级大雾（物理实验考试题库）查询，返回对应实验的预习测与出门测题目图片。\n如果有多个关键词匹配，会显示所有匹配的关键词和对应的图片。\n如果有关键词匹配但图片不存在，会显示缺失的图片文件名。\n如果没有匹配的关键词，会提示没有找到关键词。",
            reply_message=True,
        )
    else:
        found_keywords = find_keywords(name.result)
        if found_keywords:
            await send_keyword_images(found_keywords)
        else:
            await safe_send(dawu2,
                f"正在尝试AI匹配...",
                reply_message=True,
            )
            ai_keywords, error = await ai_match(name.result, KEYWORDS)

            if error:
                # 失败原因可区分：config / timeout / network / http_<状态码> / parse / unknown
                await safe_finish(dawu2, format_ai_error(error), reply_message=True)
            elif ai_keywords:
                await send_keyword_images(ai_keywords, "AI匹配到： ")
            else:
                await safe_finish(dawu2,
                    f"AI也没有找到匹配的关键词，使用'大雾2 ls'查看关键词列表",
                    reply_message=True,
                )