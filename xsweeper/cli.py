"""Command-line interface."""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .archive import load_posts
from .filters import Filter, load_id_csv, parse_date, parse_types
from .state import State
from .tiers import TIERS


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def eta(n: int, tier) -> str:
    per_day = tier.per_window * (86400 / tier.window_s)
    if tier.daily_cap:
        per_day = min(per_day, tier.daily_cap)
    days = n / per_day if per_day else float("inf")
    return f"{days:.1f} days" if days >= 1 else f"{days*24:.1f} hours"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="xsweeper", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth", help="OAuth 2.0 PKCE login with your own developer app")
    a.add_argument("--token-file", default=".xsweeper_token.json")
    a.add_argument("--port", type=int, default=8765)
    sub.add_parser("tiers", help="show pacing presets")
    r = sub.add_parser("run", help="filter archive and (with --confirm) delete")
    r.add_argument("archive", help="archive .zip, extracted folder, or tweets.js")
    r.add_argument("--max-likes", type=int)
    r.add_argument("--max-retweets", type=int)
    r.add_argument("--since", help="ISO date, inclusive")
    r.add_argument("--until", help="ISO date, exclusive")
    r.add_argument("--types", default="reply,original,retweet")
    r.add_argument("--include", action="append", default=[], help="keyword (repeatable)")
    r.add_argument("--exclude", action="append", default=[], help="keyword (repeatable)")
    r.add_argument("--ids", help="CSV of post IDs to restrict to")
    r.add_argument("--tier", choices=sorted(TIERS), default="free")
    r.add_argument("--per-window", type=int, help="override requests per 15-min window")
    r.add_argument("--daily-cap", type=int, help="override daily cap (0 = none)")
    r.add_argument("--budget", type=float, help="USD cap (payg)")
    r.add_argument("--max-wait", type=float, default=3.0, help="hours to wait for a reset")
    r.add_argument("--state", default="xsweeper_state.sqlite")
    r.add_argument("--token-file", default=".xsweeper_token.json")
    r.add_argument("--limit", type=int, help="process at most N this run")
    r.add_argument("--confirm", action="store_true", help="actually delete (default: dry run)")
    return ap


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.cmd == "auth":
        from .auth import run_login
        run_login(Path(args.token_file), args.port)
        return 0
    if args.cmd == "tiers":
        for t in TIERS.values():
            print(f"{t.name:11} {t.per_window}/{t.window_s//60}min cap={t.daily_cap} "
                  f"~${t.cost_per_delete}/del  41k ETA {eta(41000, t)}\n            {t.note}")
        return 0

    tier = TIERS[args.tier]
    if args.per_window:
        tier = replace(tier, per_window=args.per_window)
    if args.daily_cap is not None:
        tier = replace(tier, daily_cap=args.daily_cap or None)
    f = Filter(max_likes=args.max_likes, max_retweets=args.max_retweets,
               since=parse_date(args.since), until=parse_date(args.until),
               types=parse_types(args.types), include=args.include, exclude=args.exclude,
               ids=load_id_csv(args.ids) if args.ids else None)
    posts = load_posts(args.archive)
    sel = f.apply(posts)
    st = State(args.state)
    todo = [p for p in sel if st.status(p.id) not in ("done", "skipped")]
    if args.limit:
        todo = todo[: args.limit]
    by = Counter(p.type for p in sel)
    print(f"Archive posts: {len(posts)}")
    print(f"Matched: {len(sel)}  ({', '.join(f'{k} {v}' for k, v in sorted(by.items()))})")
    print(f"Already handled (state): {len(sel) - len([p for p in sel if st.status(p.id) not in ('done','skipped')])}")
    print(f"To process this run: {len(todo)}")
    print(f"Tier '{tier.name}': {tier.per_window}/15min, daily cap {tier.daily_cap}; "
          f"ETA {eta(len(todo), tier)}"
          + (f"; est. cost ${len(todo)*tier.cost_per_delete:,.2f}" if tier.cost_per_delete else ""))
    if not args.confirm:
        print("DRY RUN: nothing deleted. Add --confirm to delete.")
        return 0

    from .api import XClient
    from .auth import load_access_token
    from .runner import Runner
    tok = load_access_token(Path(args.token_file))
    if tok:
        os.environ.setdefault("X_USER_ACCESS_TOKEN", tok)
    client = XClient.from_env()
    uid = client.me() if any(p.type == "retweet" and p.retweeted_source_id for p in todo) else None
    stats = Runner(client, st, tier, user_id=uid, budget=args.budget,
                   max_wait_s=args.max_wait * 3600).run(todo)
    print(f"Run finished: {stats}; totals in state: {st.counts()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
