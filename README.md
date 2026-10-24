# XArchiveSweeper

Delete your own old X posts in bulk, straight from your X data archive, using only the
**official X API v2** and **your own developer app**. Free to use. Slow on free access,
faster as your API access improves.

- Reads the archive `.zip`, an extracted folder, or `data/tweets.js`
- Filters: `--max-likes`, `--max-retweets`, `--since/--until`, `--types reply,original,retweet`,
  `--include/--exclude` keywords, `--ids file.csv`
- Deletes with `DELETE /2/tweets/:id`; un-retweets with `DELETE /2/users/:id/retweets/:source_tweet_id`
  when the archive includes the source post ID (otherwise the retweet's own ID is deleted)
- **Dry run by default.** Nothing is deleted without `--confirm`
- Tier-aware pacing plus live `x-rate-limit-remaining` / `x-rate-limit-reset` headers and 429 handling
- Resumable SQLite state (done / failed / skipped), safe to run daily from cron or Task Scheduler
- No scraping, no internal or undocumented endpoints

## X API access and delete limits (checked October 2026)

X's docs now describe **pay-per-usage** as the self-serve model ("no subscriptions"), and
publish one set of per-user rate limits for it. Enterprise gets custom limits. The legacy
Free / Basic / Pro presets are kept for developers still on those plans; their exact
current limits are no longer published, so the presets are conservative and the live
headers win.

| `--tier` | Access | Delete limit used | Daily cap | Cost | ~41,000 deletes |
|---|---|---|---|---|---|
| `free` | Legacy Free | 1 / 15 min | 17 / day (historical write cap) | $0 | ~6.6 years |
| `basic` | Legacy Basic | 50 / 15 min | 2,400 / day | subscription | ~17 days |
| `pro` | Legacy Pro | 50 / 15 min | none | subscription | ~8.5 days |
| `payg` | Pay-per-usage (current) | 50 / 15 min per user | none | ~$0.010 per delete ("Interaction: Delete") | ~8.5 days, ~$410 |
| `enterprise` | Enterprise | custom (`--per-window N`) | none | contract | depends |

`DELETE /2/tweets/:id` and `DELETE /2/users/:id/retweets/:tweet_id` are both
**50 requests / 15 min per user** (4,800 / day max). Buying credits does not raise rate limits.

Sources:
- Rate limits: https://docs.x.com/x-api/fundamentals/rate-limits
- Pricing: https://docs.x.com/x-api/getting-started/pricing
- Delete post: https://docs.x.com/x-api/posts/delete-post
- Un-retweet: https://docs.x.com/x-api/users/unrepost-post
- OAuth 2.0 PKCE: https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code

Prices and limits change; check the Developer Console (https://console.x.com).

## Setup

1. Get your archive: X → Settings → Your account → Download an archive of your data.
2. Create a developer app at https://console.x.com (your own account).
   - User authentication settings: **Read and write**, type **Native App** (public client) or
     Web App, callback URL `http://127.0.0.1:8765/callback`.
   - Copy the OAuth 2.0 **Client ID** (and secret for confidential apps), or the OAuth 1.0a
     API key/secret plus access token/secret.
3. Install:
   ```bash
   python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env    # fill in; .env is git-ignored
   python -m xsweeper auth # OAuth 2.0 PKCE login (skip if using OAuth 1.0a keys)
   ```
   Tokens are stored in `.xsweeper_token.json` (git-ignored). Never commit them.

## Examples

```bash
# Dry run: count replies and originals with 0 or 1 likes
python -m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original

# Actually delete, slow-walking on legacy Free
python -m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original --tier free --confirm

# Pay-per-usage, stop after spending $50
python -m xsweeper run twitter-archive.zip --max-likes 1 --tier payg --budget 50 --confirm

# Only 2019 posts mentioning "crypto", except ones that say "keep"
python -m xsweeper run tweets.js --since 2019-01-01 --until 2020-01-01 --include crypto --exclude keep

# Restrict to a reviewed CSV of IDs (an "id" column or first column)
python -m xsweeper run archive.zip --ids reviewed.csv --confirm

python -m xsweeper tiers   # show presets and ETAs
```

Progress lives in `xsweeper_state.sqlite`. Re-running skips finished posts, so schedule it:

- cron: `15 3 * * * cd /path/xsweeper && .venv/bin/python -m xsweeper run archive.zip --max-likes 1 --tier free --confirm`
- Windows Task Scheduler: daily task running
  `C:\path\xsweeper\.venv\Scripts\python.exe -m xsweeper run archive.zip --max-likes 1 --tier free --confirm`
  with "Start in" set to the repo folder.

A run stops on the tier's daily cap, a budget, an auth error, or a rate-limit reset further away
than `--max-wait` hours, and picks up where it left off next time.

## Tests

```bash
pytest -q
```
Unit tests use a mocked API. An optional parser test runs against a local archive if present;
archive data is git-ignored and never committed.

## Disclaimer

Deletion is permanent. Use dry run first and review the counts. This project is not affiliated
with or endorsed by X Corp. You are responsible for following the X Developer Agreement and
Policy and for any API charges. Provided as-is under the MIT License.
