"""Post selection filters."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .archive import Post

TYPES = {"reply", "original", "retweet"}


@dataclass
class Filter:
    max_likes: int | None = None
    max_retweets: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    types: set[str] = field(default_factory=lambda: set(TYPES))
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    ids: set[str] | None = None

    def match(self, p: Post) -> bool:
        if p.type not in self.types:
            return False
        if self.ids is not None and p.id not in self.ids:
            return False
        # Retweets carry the original's counts in the archive, so like/RT caps
        # are not applied to them.
        if p.type != "retweet":
            if self.max_likes is not None and p.likes > self.max_likes:
                return False
            if self.max_retweets is not None and p.retweets > self.max_retweets:
                return False
        if self.since and p.created_at < self.since:
            return False
        if self.until and p.created_at >= self.until:
            return False
        low = p.text.lower()
        if self.include and not any(k.lower() in low for k in self.include):
            return False
        if self.exclude and any(k.lower() in low for k in self.exclude):
            return False
        return True

    def apply(self, posts: Iterable[Post]) -> list[Post]:
        return [p for p in posts if self.match(p)]


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_types(s: str) -> set[str]:
    t = {x.strip().lower() for x in s.split(",") if x.strip()}
    bad = t - TYPES
    if bad:
        raise ValueError(f"unknown type(s): {', '.join(sorted(bad))}")
    return t


def load_id_csv(path: str | Path) -> set[str]:
    """Read IDs from a CSV: an 'id' column if present, else the first column."""
    ids: set[str] = set()
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return ids
    header = [h.strip().lower() for h in rows[0]]
    col = header.index("id") if "id" in header else 0
    start = 1 if (header and not header[col].isdigit()) else 0
    for r in rows[start:]:
        if len(r) > col and r[col].strip().isdigit():
            ids.add(r[col].strip())
    return ids
