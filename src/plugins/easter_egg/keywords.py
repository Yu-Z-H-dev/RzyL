import json
from dataclasses import dataclass, field
from pathlib import Path

_keywords_path = Path(__file__).parent.parent.parent / "asserts" / "easter_egg" / "keywords.json"


@dataclass(frozen=True)
class Entity:
    """一个可被查询并输出单张图片的个体。"""

    key: str
    mode: str  # "file" = 单照片个体；"dir" = 多照片个体
    aliases: list[str] = field(default_factory=list)
    category: str | None = None  # 无 category 表示顶层个体
    enabled: bool = True  # 仅顶层个体携带开关；类内个体跟随类


@dataclass(frozen=True)
class Category:
    key: str
    display: str
    enabled: bool


@dataclass(frozen=True)
class Compound:
    """复合体：一个关键词映射到多个 target 个体。"""

    key: str
    aliases: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)


def _load_raw() -> dict:
    return json.loads(_keywords_path.read_text(encoding="utf-8"))


def load_categories() -> dict[str, Category]:
    raw = _load_raw().get("categories", {})
    return {
        key: Category(key=key, display=spec["display"], enabled=spec.get("enabled", True))
        for key, spec in raw.items()
    }


def load_entities() -> dict[str, Entity]:
    """加载个体，并过滤掉所有不可见的个体。

    可见性规则：
      - 顶层个体 -> 看自身 enabled；
      - 类内个体 -> 看所属类的 enabled（个体不单独持 enabled）。
    """
    raw = _load_raw()
    categories = {k: v.get("enabled", True) for k, v in raw.get("categories", {}).items()}
    entities: dict[str, Entity] = {}
    for key, spec in raw.get("entities", {}).items():
        category = spec.get("category")
        if category is not None and not categories.get(category, True):
            continue  # 类关闭 -> 该类个体完全不可见
        if category is None and not spec.get("enabled", True):
            continue  # 顶层个体自身关闭 -> 不可见
        entities[key] = Entity(
            key=key,
            mode=spec["mode"],
            aliases=spec.get("aliases", []),
            category=category,
            enabled=spec.get("enabled", True),
        )
    return entities


def load_compounds() -> dict[str, Compound]:
    raw = _load_raw().get("compounds", {})
    return {
        key: Compound(key=key, aliases=spec.get("aliases", []), targets=spec.get("targets", []))
        for key, spec in raw.items()
    }


def compound_visible(compound: Compound, entities: dict[str, Entity]) -> bool:
    """复合体的可见性受其 targets 约束：所有 target 个体均可见才可见。"""
    if not compound.targets:
        return False
    return all(target in entities for target in compound.targets)


MAX_HELP_EXAMPLES = 3


def build_help_examples(
    entities: dict[str, Entity],
    compounds: dict[str, Compound],
    limit: int = MAX_HELP_EXAMPLES,
) -> list[str]:
    """挑出当前真正可用的彩蛋名，供 help 文本当示例。

    只从可见集合里选（entities 已由 load_entities 按开关过滤，复合体再过一遍
    compound_visible），因此示例永远不会指向被禁用或删除的彩蛋。

    选取顺序：每个已开启的类各取一个 -> 顶层个体 -> 可见复合体。
    同类内取 keywords.json 中声明顺序最靠前的那个，所以把想展示的名字排在前面即可。
    """
    examples: list[str] = []

    def _add(name: str) -> None:
        if name and name not in examples and len(examples) < limit:
            examples.append(name)

    # 1) 每个已开启的类各取一个代表，体现"彩蛋是分类的"
    picked_categories: set[str] = set()
    for entity in entities.values():
        if entity.category is None or entity.category in picked_categories:
            continue
        if entity.aliases:
            picked_categories.add(entity.category)
            _add(entity.aliases[0])

    # 2) 顶层个体（不隶属任何类，始终可用）
    for entity in entities.values():
        if entity.category is None and entity.aliases:
            _add(entity.aliases[0])

    # 3) 可见复合体（如「四大善人」，其 targets 全可见时才出现）
    for compound in compounds.values():
        if compound_visible(compound, entities) and compound.aliases:
            _add(compound.aliases[0])

    return examples