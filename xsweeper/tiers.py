"""Pacing presets per X API access tier.

Sources (checked Oct 2026):
- https://docs.x.com/x-api/fundamentals/rate-limits  (DELETE /2/tweets/:id and
  DELETE /2/users/:id/retweets/:tweet_id: 50 requests / 15 min per user)
- https://docs.x.com/x-api/getting-started/pricing   (pay-per-usage, no subscriptions)

Live x-rate-limit-* headers always override these presets downward.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    per_window: int          # max requests per window
    window_s: int            # window length in seconds
    daily_cap: int | None    # stop for the day after this many (None = no cap)
    cost_per_delete: float   # USD estimate, 0 if not billed per request
    note: str


TIERS = {
    "free": Tier("free", 1, 15 * 60, 17, 0.0,
                 "Legacy Free: write cap historically ~17 requests/24h per user. "
                 "Slow-walk; run once a day."),
    "basic": Tier("basic", 50, 15 * 60, 2400, 0.0,
                  "Legacy Basic subscription: documented 50/15min per user; capped at "
                  "2,400/day to stay friendly."),
    "pro": Tier("pro", 50, 15 * 60, None, 0.0,
                "Legacy Pro subscription: 50/15min per user, no daily cap."),
    "payg": Tier("payg", 50, 15 * 60, None, 0.010,
                 "Current pay-per-usage: 50/15min per user; ~$0.010 per delete "
                 "(Interaction: Delete). Use --budget to cap spend."),
    "enterprise": Tier("enterprise", 50, 15 * 60, None, 0.0,
                       "Custom limits. Starts at 50/15min; raise with --per-window "
                       "and let headers drive it."),
}
