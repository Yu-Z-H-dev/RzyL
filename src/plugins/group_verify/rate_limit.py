"""进程内限流与去重（无外部依赖：纯 asyncio + 内存字典）。

qq.ustc.life 的 FAQ 要求任意两次请求间隔 ≥ 1 秒，而入群申请可能并发到达，
所以这里做的是**全局串行排队**：所有请求先过 IntervalLimiter.acquire()，
拿到槽位才允许发请求。队列满 / 等待超时一律返回 False，由调用方转人工，
避免把请求无限堆积成重试风暴。

FlagCache 用于应对事件重放或重连：同一个 flag 在 TTL 内只处理一次。
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class IntervalLimiter:
    """全局最小间隔限流器。

    - min_interval：相邻两次放行的最小间隔（秒）
    - queue_max_size：允许同时在排队的请求数上限，超出直接拒绝（转人工）
    - wait_timeout：单个请求最长排队时间（秒），超时也转人工
    """

    def __init__(self, min_interval: float, queue_max_size: int, wait_timeout: float) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.queue_max_size = max(1, int(queue_max_size))
        self.wait_timeout = max(self.min_interval, float(wait_timeout))
        self._lock = asyncio.Lock()
        self._waiting = 0
        self._next_allowed = 0.0
        # 便于测试注入假时钟；生产用单调时钟，不受系统时间跳变影响
        self.clock = time.monotonic

    @property
    def waiting(self) -> int:
        """当前在排队（含持有槽位）的请求数。"""
        return self._waiting

    async def acquire(self) -> bool:
        """申请一个发送槽位。True=可以发；False=队列满或等待超时。"""
        if self._waiting >= self.queue_max_size:
            logger.warning(
                "限流队列已满（waiting=%d/%d），本次请求转人工",
                self._waiting,
                self.queue_max_size,
            )
            return False

        self._waiting += 1
        try:
            deadline = self.clock() + self.wait_timeout
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    logger.warning("限流排队超时（>%.1fs），本次请求转人工", self.wait_timeout)
                    return False
                try:
                    await asyncio.wait_for(self._lock.acquire(), timeout=remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    logger.warning("限流排队超时（>%.1fs），本次请求转人工", self.wait_timeout)
                    return False
                try:
                    now = self.clock()
                    wait = self._next_allowed - now
                    if wait <= 0:
                        # 只在真正放行时推进时间轴，保证「相邻两次发送」间隔 ≥ min_interval
                        self._next_allowed = now + self.min_interval
                        return True
                finally:
                    self._lock.release()
                # 还不到时间：释放锁后小睡，避免所有人空转抢锁
                await asyncio.sleep(min(wait, self.min_interval))
        finally:
            self._waiting -= 1


class FlagCache:
    """短期「已处理 flag」集合，应对事件重放/重连导致的重复审批。"""

    def __init__(self, ttl_seconds: float = 600.0, max_size: int = 1024) -> None:
        self.ttl = max(1.0, float(ttl_seconds))
        self.max_size = max(1, int(max_size))
        self._seen: dict[str, float] = {}
        self.clock = time.monotonic

    def __len__(self) -> int:
        return len(self._seen)

    def first_seen(self, flag: str) -> bool:
        """首次见到该 flag 返回 True；重复、或 flag 为空返回 False。"""
        if not flag:
            return False
        now = self.clock()
        self._prune(now)
        if flag in self._seen:
            return False
        self._seen[flag] = now
        if len(self._seen) > self.max_size:
            self._prune(now, force=True)
        return True

    def _prune(self, now: float, force: bool = False) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts > self.ttl]
        for k in expired:
            self._seen.pop(k, None)
        if force and len(self._seen) > self.max_size:
            # 仍然超限（TTL 内涌入过多）时按时间从旧到新丢弃
            for k, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[
                : len(self._seen) - self.max_size
            ]:
                self._seen.pop(k, None)
