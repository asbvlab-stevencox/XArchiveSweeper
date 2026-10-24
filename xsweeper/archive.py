"""Parse an X data archive (zip or tweets.js) into Post records."""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

_PREFIX = re.compile(r"^\s*window\.YTD\.[A-Za-z0-9_]+\.part\d+\s*=\s*", re.S)
_TWEET_FILE = re.compile(r"(^|/)data/tweets(-part\d+)?\.js$")


@dataclass(frozen=True)
class Post:
    id: str
    created_at: datetime
    type: str  # "reply" | "original" | "retweet"
    likes: int
    retweets: int
    text: str
    in_reply_to: str | None = None
    retweeted_source_id: str | None = None


def _load_js(text: str) -> list:
    return json.loads(_PREFIX.sub("", text, count=1))


def classify(t: dict) -> str:
    if t.get("retweeted_status") or str(t.get("full_text", "")).startswith("RT @"):
        return "retweet"
    if t.get("in_reply_to_status_id_str") or t.get("in_reply_to_status_id"):
        return "reply"
    return "original"


def to_post(item: dict) -> Post:
    t = item.get("tweet", item)
    src = (t.get("retweeted_status") or {}).get("id_str")
    return Post(
        id=str(t.get("id_str") or t["id"]),
        created_at=datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y"),
        type=classify(t),
        likes=int(t.get("favorite_count", 0) or 0),
        retweets=int(t.get("retweet_count", 0) or 0),
        text=t.get("full_text", t.get("text", "")),
        in_reply_to=t.get("in_reply_to_status_id_str"),
        retweeted_source_id=src,
    )


def _texts(path: Path) -> Iterator[str]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if _TWEET_FILE.search(n))
            if not names:
                raise ValueError("no data/tweets.js found in archive zip")
            for n in names:
                with z.open(n) as f:
                    yield io.TextIOWrapper(f, encoding="utf-8").read()
    elif path.is_dir():
        files = sorted(path.rglob("tweets*.js"))
        if not files:
            raise ValueError(f"no tweets*.js under {path}")
        for p in files:
            yield p.read_text(encoding="utf-8")
    else:
        yield path.read_text(encoding="utf-8")


def load_posts(path: str | Path) -> list[Post]:
    posts: dict[str, Post] = {}
    for text in _texts(Path(path)):
        for item in _load_js(text):
            p = to_post(item)
            posts[p.id] = p
    return sorted(posts.values(), key=lambda p: p.created_at)
