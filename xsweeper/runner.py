"""Tier-aware, header-adaptive delete loop."""
from __future__ import annotations

import time
from typing import Callable

from .api import XClient
from .archive import Post
from .state import State
from .tiers import Tier


class Runner:
    def __init__(self, client: XClient, state: State, tier: Tier, user_id: str | None = None,
                 budget: float | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time, log: Callable[[str], None] = print,
                 max_wait_s: float = 3 * 3600):
        self.c, self.st, self.tier = client, state, tier
        self.user_id = user_id
        self.budget = budget
        self.sleep, self.clock, self.log = sleep, clock, log
        self.max_wait_s = max_wait_s
        self.interval = tier.window_s / max(tier.per_window, 1)

    def _wait_until(self, reset: int | None, why: str) -> bool:
        wait = max((reset or self.clock() + self.tier.window_s) - self.clock(), 0) + 2
        if wait > self.max_wait_s:
            self.log(f"{why}: reset in {wait/60:.0f} min > max wait; stopping. Re-run later.")
            return False
        self.log(f"{why}: sleeping {wait:.0f}s until reset")
        self.sleep(wait)
        return True

    def run(self, posts: list[Post]) -> dict[str, int]:
        stats = {"deleted": 0, "failed": 0, "skipped": 0}
        spent = 0.0
        for p in posts:
            if self.st.status(p.id) in ("done", "skipped"):
                continue
            if self.tier.daily_cap is not None and self.st.used_today() >= self.tier.daily_cap:
                self.log(f"Daily cap {self.tier.daily_cap} reached for tier '{self.tier.name}'; "
                         "resume tomorrow.")
                break
            if self.budget is not None and spent + self.tier.cost_per_delete > self.budget:
                self.log(f"Budget ${self.budget:.2f} reached; stopping.")
                break
            while True:
                if p.type == "retweet" and p.retweeted_source_id and self.user_id:
                    r = self.c.unretweet(self.user_id, p.retweeted_source_id)
                else:
                    r = self.c.delete_post(p.id)
                if r.status == 429:
                    if not self._wait_until(r.reset, "429 rate limited"):
                        return stats
                    continue
                break
            self.st.bump_today()
            spent += self.tier.cost_per_delete
            if r.ok:
                self.st.mark(p.id, "done")
                stats["deleted"] += 1
            elif r.status == 404:
                self.st.mark(p.id, "skipped", "already gone (404)")
                stats["skipped"] += 1
            else:
                self.st.mark(p.id, "failed", f"{r.status} {r.detail}")
                stats["failed"] += 1
                if r.status in (401, 403):
                    self.log(f"Auth error {r.status}: {r.detail}; stopping.")
                    return stats
            if r.remaining == 0:
                if not self._wait_until(r.reset, "window exhausted"):
                    return stats
            else:
                self.sleep(self.interval)
        return stats
