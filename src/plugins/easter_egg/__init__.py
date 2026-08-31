import logging
import random
import time
from collections import defaultdict
from pathlib import Path

from nonebot import require
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment

from .ai_match import ai_chat, ai_match
from .keywords import (
    Compound,
    Entity,
    load_categories,
    load_entities,
    load_compounds,
    compound_visible,
)
from .random_text import load_random_text as try_load_random_text
from src.utils.safe_send import safe_finish, safe_send

require("nonebot_plugin_alconna")

from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna

logger = logging.getLogger(__name__)

__plugin_meta__ = PluginMetadata(
    name="彩蛋插件",
    description="迪士尼角色彩蛋查询与随机文本",
    usage="发送 彩蛋 <角色名> 查询图片；发送 彩蛋 ls 查看所有可用彩蛋",
    type="application",
    supported_adapters={"~onebot.v11"},
)

EASTER_EGG_IMAGE_DIR = Path(__file__).parent.parent.parent / "asserts" / "easter_egg"

SUPPORTED_IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif",
)

_collectors = (".ipynb_checkpoints", "__pycache__")


def _list_images(directory: Path) -> list[Path]:
    """列出目录内受支持的图片文件（跳过隐藏项与缓存目录）。"""
    return [
        f for f in directory.iterdir()
        if f.is_file()
        and f.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        and not f.name.startswith(".")
        and f.parent.name not in _collectors
    ]


def _resolve_entity_dir(entity: Entity) -> Path:
    """根据个体定位其资源目录：类内个体在 easter_egg/<category>/<key>，顶层个体在 easter_egg/<key>。"""
    if entity.category is not None:
        return EASTER_EGG_IMAGE_DIR / entity.category / entity.key
    return EASTER_EGG_IMAGE_DIR / entity.key


def resolve_entity_image(entity: Entity) -> Path | None:
    """解析个体的图片（个体查询一律只输出一张）。

    mode="file"：单照片个体，返回唯一文件（探测各种扩展名）；
    mode="dir"：多照片个体，在该个体目录内随机挑一张。
    """
    base = _resolve_entity_dir(entity)

    if entity.mode == "dir":
        if base.is_dir():
            images = _list_images(base)
            if images:
                return random.choice(images)
        return None

    # mode == "file"：base 是「目录/key」，探测 base + 各扩展名
    for ext in SUPPORTED_IMAGE_EXTENSIONS:
        path = Path(f"{base}{ext}")
        if path.is_file():
            return path
    return None


def find_entities(text: str, entities: dict[str, Entity]) -> list[Entity]:
    """按别名直接相等匹配（而非子串包含），同一输入可命中多个个体。"""
    found: list[Entity] = []
    for entity in entities.values():
        if any(alias == text for alias in entity.aliases):
            found.append(entity)
    return found


def find_compounds(text: str, compounds: dict[str, Compound], entities: dict[str, Entity]) -> list[tuple[str, list[Entity]]]:
    """按别名直接相等匹配复合体，返回 (compound_key, [可见的 target 个体])。"""
    found = []
    for key, compound in compounds.items():
        if any(alias == text for alias in compound.aliases):
            if compound_visible(compound, entities):
                targets = [entities[t] for t in compound.targets if t in entities]
                found.append((key, targets))
    return found


def build_ai_keywords(entities: dict[str, Entity], compounds: dict[str, Compound]) -> dict[str, list[str]]:
    """把可见的个体与复合体整理成 AI 模糊匹配用的 {key: aliases} 字典。"""
    keywords: dict[str, list[str]] = {}
    for key, entity in entities.items():
        keywords[key] = list(entity.aliases)
    for key, compound in compounds.items():
        if compound_visible(compound, entities):
            keywords[key] = list(compound.aliases)
    return keywords


# AI 路径（模糊匹配 + 对话回退）会消耗 API 额度，按用户限流，与 dawu 保持一致
RATE_LIMIT: defaultdict[int, list[float]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = 10


def check_rate_limit(user_id: int) -> bool:
    """检查并记录请求：裁剪 60 秒外的记录，未超限则记入当前时间戳并放行。"""
    now = time.time()
    user_requests = [t for t in RATE_LIMIT[user_id] if now - t < 60]
    if len(user_requests) >= MAX_REQUESTS_PER_MINUTE:
        RATE_LIMIT[user_id] = user_requests
        return False
    user_requests.append(now)
    RATE_LIMIT[user_id] = user_requests
    return True


async def _append_entity_messages(entity: Entity, messages: list) -> None:
    """解析单个个体的图片并追加到消息列表（缺失则追加提示）。"""
    path = await _resolve_image_or_none(entity)
    if path:
        messages.append(f"{entity.aliases[0]}:")
        messages.append(MessageSegment.image(path))
    else:
        messages.append(f"{entity.aliases[0]}: 图片文件不存在")


async def send_ai_matched_images(ai_keys: list[str], entities: dict[str, Entity], compounds: dict[str, Compound]) -> None:
    """根据 AI 返回的 key 列表解析并发出图片（个体或复合体），无可用图片时给出提示。"""
    image_messages: list = []
    seen: set[str] = set()
    for key in ai_keys:
        if key in seen:
            continue
        seen.add(key)
        if key in entities:
            await _append_entity_messages(entities[key], image_messages)
        elif key in compounds and compound_visible(compounds[key], entities):
            for target_key in compounds[key].targets:
                if target_key in entities:
                    await _append_entity_messages(entities[target_key], image_messages)

    if not image_messages:
        await safe_finish(caidan, "AI 匹配到关键词但未找到可用图片", reply_message=True)
        return

    messages: list = ["AI 匹配到：", *image_messages]
    if random_text := try_load_random_text():
        messages.append(random_text)
    await safe_finish(caidan, Message(messages))


caidan = on_alconna(
    Alconna("彩蛋", Args["name", str]),
    priority=1,
    block=True,
)


async def _resolve_image_or_none(entity: Entity) -> Path | None:
    return resolve_entity_image(entity)


@caidan.handle()
async def _(event: MessageEvent, name: Match[str]):
    logger.info(f"收到彩蛋请求: 群{getattr(event, 'group_id', '私聊')}, 用户{event.user_id}, 内容{name.result}")

    if not name.available:
        await safe_finish(caidan, "请输入名称，例如: 彩蛋 玲娜贝儿")
        return

    raw_text = name.result.strip()

    entities = load_entities()
    compounds = load_compounds()

    # 彩蛋 help: 帮助信息
    if raw_text == "help":
        await safe_finish(caidan,
            "使用方法: 彩蛋 <名称>\n例如: 彩蛋 玲娜贝儿 / 彩蛋 四大善人\n\n"
            "- 精确匹配彩蛋名称（别名直接相等匹配），返回对应图片\n"
            "- 未精确匹配时，自动使用 AI 模糊匹配彩蛋\n"
            "- 若仍无匹配，会作为对话机器人回复你的发言\n"
            "- 发送「彩蛋 ls」查看所有可用彩蛋",
            reply_message=True,
        )
        return

    # 彩蛋 ls: 按类分组列出所有可见彩蛋
    if raw_text == "ls":
        categories = load_categories()
        output_lines: list[str] = []

        # 顶层个体（无 category）
        top_entities = [e for e in entities.values() if e.category is None]
        if top_entities:
            output_lines.append("[顶层] " + ", ".join(e.aliases[0] for e in top_entities))

        # 各类内个体
        for cat_key, cat in categories.items():
            if not cat.enabled:
                continue
            members = [e for e in entities.values() if e.category == cat_key]
            if members:
                output_lines.append(
                    f"[{cat.display}] " + ", ".join(e.aliases[0] for e in members)
                )

        # 复合体（可见的）
        visible_compounds = [
            c for c in compounds.values() if compound_visible(c, entities)
        ]
        if visible_compounds:
            output_lines.append(
                "[组合] " + ", ".join(c.aliases[0] for c in visible_compounds)
            )

        if not output_lines:
            await safe_finish(caidan, "暂无可用彩蛋")
            return
        await safe_finish(caidan, "\n".join(output_lines))
        return

    # 复合体匹配（优先，因为复合体别名可能与个体别名重叠）
    compound_matches = find_compounds(raw_text, compounds, entities)
    # 个体匹配
    entity_matches = find_entities(raw_text, entities)

    # 精确匹配命中：直接出图
    if compound_matches or entity_matches:
        messages: list = []
        for _, targets in compound_matches:
            for target in targets:
                await _append_entity_messages(target, messages)
        for entity in entity_matches:
            await _append_entity_messages(entity, messages)
        if random_text := try_load_random_text():
            messages.append(random_text)
        await safe_finish(caidan, Message(messages))
        return

    # 精确未命中：AI 模糊匹配（消耗 API 额度，按用户限流）
    if not check_rate_limit(event.user_id):
        await safe_finish(caidan, "请求过于频繁，请稍后再试（每分钟最多10次请求）")
        return

    await safe_send(caidan, "正在思考...")

    ai_keywords = build_ai_keywords(entities, compounds)
    ai_keys, error = await ai_match(raw_text, ai_keywords)

    if error:
        if error == "config":
            await safe_finish(caidan, "AI 匹配服务未配置，暂无法使用模糊匹配，请联系管理员", reply_message=True)
        else:
            await safe_finish(caidan, "AI 匹配服务暂时不可用，请稍后再试", reply_message=True)
        return

    if ai_keys:
        # AI 命中彩蛋关键词：出图
        await send_ai_matched_images(ai_keys, entities, compounds)
        return

    # AI 也未匹配（视为用户在「彩蛋」后说了无关/无意义的话）：对话回退，引用该用户的发言
    reply, chat_error = await ai_chat(raw_text)
    if chat_error:
        if chat_error == "config":
            await safe_finish(caidan, "对话服务未配置，暂无法使用", reply_message=True)
        else:
            await safe_finish(caidan, "对话服务暂时不可用，请稍后再试", reply_message=True)
        return
    if reply:
        await safe_finish(caidan, reply, reply_message=True)
    else:
        await safe_finish(caidan, "（没有想好要说什么）", reply_message=True)