"""学号名单核验：只读 ustc_bot 的 GetNameList 数据。

用途有两个：
  1. 全码学号做存在性核验（可选，见配置 require_namelist）；
  2. 掩码学号（站点允许只展示前几位）用「可见前缀能否在名单里找到人」来判定
     —— 这正是站点 FAQ 推荐的用法：要求对方必须展示到某几位。

实现要点：
  - 惰性加载：首次真正需要时才读文件，读完只保留允许届别的 10 位 PB 学号，
    随即丢掉原始大字典（identity.json 约 31MB），避免常驻内存。
  - 文件缺失/损坏 -> 返回 None 并打 ERROR，调用方退化为「只按正则」，
    不会因为名单不可用而把真实申请人全部拒掉。
"""

from __future__ import annotations

import asyncio
import json
import logging
from bisect import bisect_left
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

# 名单里合法学号的形态：PB + 8 位数字
_PREFIX = "PB"
_LEN = 10


class StudentIdIndex:
    """有序学号集合，支持存在性与前缀查询。"""

    def __init__(self, ids: Iterable[str]) -> None:
        self._ids: list[str] = sorted({i for i in ids if len(i) == _LEN and i.startswith(_PREFIX)})

    def __len__(self) -> int:
        return len(self._ids)

    def exists(self, student_id: str) -> bool:
        i = bisect_left(self._ids, student_id)
        return i < len(self._ids) and self._ids[i] == student_id


def _build_index(path: Path, cohorts: Iterable[int]) -> StudentIdIndex | None:
    years = {f"{int(c) % 100:02d}" for c in cohorts}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("学号名单不存在：%s（全码学号将无法核验，申请会转人工）", path)
        return None
    except Exception as exc:  # noqa: BLE001 - 名单损坏不应拖垮机器人
        logger.error("学号名单读取失败：%s: %s", type(exc).__name__, exc)
        return None

    if not isinstance(raw, dict):
        logger.error("学号名单格式异常：期望 {学号: {...}}，实际 %s", type(raw).__name__)
        return None

    ids = [
        key
        for key in raw
        if isinstance(key, str)
        and len(key) == _LEN
        and key.startswith(_PREFIX)
        and key[2:].isdigit()
        and key[2:4] in years
    ]
    del raw  # 立刻释放原始大字典
    logger.info("学号名单已载入：%d 条（届别 %s）", len(ids), sorted(years))
    return StudentIdIndex(ids)


class LazyStudentIndex:
    """惰性、线程安全（同事件循环内串行）地提供 StudentIdIndex。"""

    def __init__(self, path: str | Path, cohorts: Iterable[int]) -> None:
        self.path = Path(path)
        self.cohorts = list(cohorts)
        self._index: StudentIdIndex | None = None
        self._loaded = False
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def get(self) -> StudentIdIndex | None:
        if self._loaded:
            return self._index
        async with self._lock:
            if not self._loaded:
                loop = asyncio.get_running_loop()
                # 解析 31MB JSON 会阻塞数百毫秒，放到线程池里做
                self._index = await loop.run_in_executor(
                    None, _build_index, self.path, tuple(self.cohorts)
                )
                self._loaded = True
        return self._index
