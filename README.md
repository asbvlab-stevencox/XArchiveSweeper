# XArchiveSweeper

A free, open-source command-line tool that **deletes your own X posts in bulk**, driven by
your downloaded X data archive. It picks posts by filters such as like count, date, type, or
keywords. Then it deletes them through the **official X API v2** with **your own developer
app**. It runs slowly on free access and faster on higher API tiers.

> **Deletion is permanent.** The tool does a dry run unless you pass `--confirm`.

---

## Contents

1. [What it does](#what-it-does)
2. [Requirements and install](#requirements-and-install)
3. [Getting X API credentials](#getting-x-api-credentials-step-by-step)
4. [Preparing the archive or a candidate list](#preparing-the-archive-or-a-candidate-list)
5. [Dry run vs `--confirm`](#dry-run-vs---confirm)
6. [Tiers, pacing and expected time](#tiers-pacing-and-expected-time)
7. [Command reference](#command-reference)
8. [Resuming: the SQLite state file](#resuming-the-sqlite-state-file)
9. [Running unattended](#running-unattended)
10. [Troubleshooting](#troubleshooting)
11. [Safety notes](#safety-notes)
12. [Tests](#tests)
13. [License](#license)

---

## What it does

- Reads your X archive as the `.zip`, an extracted folder, or just `data/tweets.js`.
- Sorts each post into `reply`, `original`, or `retweet`.
- Selects posts with filters: max likes, max retweets, date range, type, include or exclude
  keywords, or an explicit list of IDs in a CSV.
- Deletes each selected post with `DELETE /2/tweets/:id`. A retweet is undone with
  `DELETE /2/users/:id/retweets/:source_tweet_id` when the archive has the source post ID.
  Otherwise the retweet's own ID is deleted.
- Paces itself to your tier and reads X's live `x-rate-limit-remaining` and
  `x-rate-limit-reset` headers. On HTTP 429 it waits for the reset.
- Saves progress in a local SQLite file, so you can stop at any point and pick up later.
- Uses only documented API endpoints. It does no scraping and has no browser automation.

A typical use: *"Delete every reply and original post that got 0 or 1 likes."*

```bash
python -m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original --confirm
```

## Requirements and install

- Python **3.10 or newer** (`python --version`)
- Git, or download the repo as a ZIP from GitHub
- An X account and a developer app on that account (see the next section)

```bash
git clone https://github.com/asbvlab-stevencox/XArchiveSweeper.git
cd XArchiveSweeper

python -m venv .venv
# macOS / Linux:
. .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

The dependencies are `requests` and `requests-oauthlib`. Check that it works:

```bash
python -m xsweeper --help
python -m xsweeper tiers
```

## Getting X API credentials (step by step)

You use **your own** developer app, so your keys never leave your machine.

1. Sign in at **https://console.x.com** (the X Developer Console) with the account that owns
   the posts.
2. Sign up for API access, then pick a plan: legacy Free, Basic, Pro, pay-per-usage, or
   Enterprise. Your plan decides the `--tier` you use (see [Tiers](#tiers-pacing-and-expected-time)).
3. **Create a Project and an App.**
4. Open the app's **User authentication settings** and set:
   - **App permissions:** **Read and write**. Deleting needs write access.
   - **Type of App:** **Native App** (public client, no secret needed) or **Web App**
     (confidential client with a client secret).
   - **Callback URI / Redirect URL:** `http://127.0.0.1:8765/callback`
   - **Website URL:** any valid URL, such as this repo's URL.
5. Save the settings. Then open **Keys and tokens**.
6. Copy the example env file and fill in **one** of the two options:

   ```bash
   cp .env.example .env        # Windows: copy .env.example .env
   ```

   **Option A: OAuth 2.0 PKCE (recommended)**

   ```ini
   X_CLIENT_ID=your-oauth2-client-id
   X_CLIENT_SECRET=            # only for Web App (confidential) clients
   # X_REDIRECT_URI=http://127.0.0.1:8765/callback   # only if you changed it
   ```

   Then log in once:

   ```bash
   python -m xsweeper auth
   ```

   A browser opens. Approve access, and the tokens are saved to `.xsweeper_token.json`. The
   scopes requested are `tweet.read tweet.write users.read offline.access`. Because of
   `offline.access`, the tool refreshes the token on its own at the start of each run, so
   scheduled runs keep working. If port 8765 is taken, use `python -m xsweeper auth --port 9000`
   and register `http://127.0.0.1:9000/callback` in the app.

   **Option B: OAuth 1.0a user keys**

   Generate the **API Key and Secret** and an **Access Token and Secret** on the Keys and tokens
   page. Make sure the token was created *after* you set Read and write, or it stays
   read-only.

   ```ini
   X_API_KEY=...
   X_API_SECRET=...
   X_ACCESS_TOKEN=...
   X_ACCESS_TOKEN_SECRET=...
   ```

   You don't need `auth` with this option.

If both are present, the OAuth 2.0 token from `.xsweeper_token.json` is used. `.env` and
`.xsweeper_token.json` are git-ignored. **Never commit or share them.**

## Preparing the archive or a candidate list

1. On X, go to **Settings → Your account → Download an archive of your data**. X can take a
   day or more to prepare it.
2. Download the `.zip` and keep it local. You can pass any of these:
   - the `.zip` itself: `run twitter-archive.zip`
   - the extracted folder: `run ./twitter-archive/`
   - the posts file alone: `run ./twitter-archive/data/tweets.js`
3. The like and retweet counts are **as of when you made the archive**. A newer archive gives
   newer counts.

**Optional: a reviewed candidate list.** To check the list by hand first, put the post IDs in
a CSV. It can have an `id` column, or the IDs can sit in the first column, with or without a
header. Pass the file with `--ids`. Only posts that are in the archive **and** in the CSV
(and that pass any other filters) are processed.

```csv
id
1234567890123456789
1234567890123456790
```

Archive files, CSVs and `data/` are git-ignored, so your data stays out of the repo.

## Dry run vs `--confirm`

Without `--confirm`, **nothing is deleted** and no credentials are needed. The tool prints:

```
Archive posts: 44000
Matched: 41000  (original 300, reply 40700)
Already handled (state): 0
To process this run: 41000
Tier 'free': 1/15min, daily cap 17; ETA 2411.8 days
DRY RUN: nothing deleted. Add --confirm to delete.
```

Tune the filters until the numbers look right. Then add `--confirm` to the same command.

## Tiers, pacing and expected time

Pick the `--tier` that matches your API plan (the default is `free`). The tool spaces requests
evenly across each 15-minute window (`15 min ÷ per-window` seconds apart). It stops early if
the live headers say the window is used up.

| `--tier` | Access | Pace | Daily cap | Cost estimate | ~1,000 posts | ~41,000 posts |
|---|---|---|---|---|---|---|
| `free` | Legacy Free | 1 / 15 min | 17 / day | $0 | ~59 days | ~6.6 years |
| `basic` | Legacy Basic | 50 / 15 min | 2,400 / day | subscription | ~5 hours | ~17 days |
| `pro` | Legacy Pro | 50 / 15 min | none (4,800/day max) | subscription | ~5 hours | ~8.5 days |
| `payg` | Pay-per-usage (current self-serve) | 50 / 15 min | none (4,800/day max) | ~$0.010 per delete | ~5 hours, ~$10 | ~8.5 days, ~$410 |
| `enterprise` | Enterprise | 50 / 15 min to start | none | contract | depends | depends |

Notes:

- X documents both delete endpoints at **50 requests per 15 minutes per user**. Buying more
  credits does not raise that limit.
- `free` is a slow walk: about 17 deletes a day, which takes about 4 hours of pacing. Running
  it once a day from a scheduler is the easiest way.
- `payg` charges per request. Use `--budget 25` to stop before you spend more than $25. The
  dry run shows an estimated cost.
- `enterprise` and custom plans can raise the pace with `--per-window N`. Live headers still
  slow things down if needed.
- Override any preset with `--per-window N` and `--daily-cap N` (`--daily-cap 0` means no cap).
- Run `python -m xsweeper tiers` to see the presets and ETAs.

Limits and prices change, so check your plan in the Developer Console. Sources (checked
October 2026):
[rate limits](https://docs.x.com/x-api/fundamentals/rate-limits),
[pricing](https://docs.x.com/x-api/getting-started/pricing),
[delete post](https://docs.x.com/x-api/posts/delete-post),
[un-retweet](https://docs.x.com/x-api/users/unrepost-post),
[OAuth 2.0 PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code).

## Command reference

```
python -m xsweeper auth  [--token-file .xsweeper_token.json] [--port 8765]
python -m xsweeper tiers
python -m xsweeper run ARCHIVE [options]
```

`run` options:

| Flag | Default | Meaning |
|---|---|---|
| `ARCHIVE` | (required) | archive `.zip`, extracted folder, or `tweets.js` |
| `--max-likes N` | none | only posts with at most N likes |
| `--max-retweets N` | none | only posts with at most N retweets |
| `--since YYYY-MM-DD` | none | posts on or after this date (inclusive) |
| `--until YYYY-MM-DD` | none | posts before this date (exclusive) |
| `--types LIST` | `reply,original,retweet` | comma-separated post types to include |
| `--include WORD` | none | text must contain the keyword (repeatable) |
| `--exclude WORD` | none | skip posts containing the keyword (repeatable) |
| `--ids FILE.csv` | none | restrict to IDs listed in a CSV |
| `--tier NAME` | `free` | `free`, `basic`, `pro`, `payg`, `enterprise` |
| `--per-window N` | tier preset | override requests per 15-minute window |
| `--daily-cap N` | tier preset | override the daily cap (`0` = none) |
| `--budget USD` | none | stop before the estimated spend goes over this amount (`payg`) |
| `--max-wait HOURS` | `3` | longest wait for a rate-limit reset before the run stops |
| `--state FILE` | `xsweeper_state.sqlite` | progress database |
| `--token-file FILE` | `.xsweeper_token.json` | OAuth 2.0 token file |
| `--limit N` | none | process at most N posts this run |
| `--confirm` | off | **actually delete**. Without it, the run is a dry run |

Examples:

```bash
# Replies and originals with 0 or 1 likes, dry run
python -m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original

# Same, for real, slow-walking on Free
python -m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original --tier free --confirm

# Pay-per-usage, stop at $50
python -m xsweeper run twitter-archive.zip --max-likes 1 --tier payg --budget 50 --confirm

# 2019 posts that mention "crypto" but not "keep"
python -m xsweeper run tweets.js --since 2019-01-01 --until 2020-01-01 --include crypto --exclude keep

# A reviewed CSV of IDs, 100 at a time
python -m xsweeper run archive.zip --ids reviewed.csv --limit 100 --confirm
```

## Resuming: the SQLite state file

Every attempt is saved in `xsweeper_state.sqlite`, or the file you name with `--state`:

- `done`: deleted
- `skipped`: already gone (404)
- `failed`: any other error, saved with the status code and message

On the next run, posts marked `done` or `skipped` are left out. Posts marked `failed` are
tried again. The daily-cap counter is kept in the same file and resets at midnight UTC.

A run stops, and the next run picks up where it left off, when:

- the tier's daily cap is reached,
- `--budget` is reached,
- the API returns 401 or 403 (an auth problem),
- a rate-limit reset is further away than `--max-wait` hours,
- or you press Ctrl+C.

To see progress:

```bash
sqlite3 xsweeper_state.sqlite "SELECT status, COUNT(*) FROM posts GROUP BY status;"
```

Keep the same state file for the same archive. Deleting the file only makes the tool retry
posts, which come back as 404 and get marked `skipped`.

## Running unattended

Always run from the repo folder so `.env`, the token file and the state file are found. Use
the same command you checked with the dry run, plus `--confirm`.

### Windows Task Scheduler

1. Open **Task Scheduler → Create Task**.
2. **General:** select "Run whether user is logged on or not".
3. **Triggers:** Daily, at a time you choose. On `basic` or faster you can repeat it every
   few hours.
4. **Actions → Start a program:**
   - Program: `C:\path\to\XArchiveSweeper\.venv\Scripts\python.exe`
   - Arguments: `-m xsweeper run twitter-archive.zip --max-likes 1 --types reply,original --tier free --confirm`
   - Start in: `C:\path\to\XArchiveSweeper`
5. **Settings:** select "Do not start a new instance" if the task is already running.

To keep a log, use a `.bat` wrapper:

```bat
cd /d C:\path\to\XArchiveSweeper
.venv\Scripts\python.exe -m xsweeper run twitter-archive.zip --max-likes 1 --tier free --confirm >> sweep.log 2>&1
```

### cron (macOS / Linux)

```cron
# every day at 03:15
15 3 * * * cd /path/to/XArchiveSweeper && .venv/bin/python -m xsweeper run twitter-archive.zip --max-likes 1 --tier free --confirm >> sweep.log 2>&1
```

To make sure only one run happens at a time, add `flock -n /tmp/xsweeper.lock` before the
command.

### nohup / tmux (one long run)

On `pro` or `payg`, a single run can go for days:

```bash
nohup .venv/bin/python -m xsweeper run twitter-archive.zip --max-likes 1 --tier payg --budget 100 --max-wait 6 --confirm > sweep.log 2>&1 &
tail -f sweep.log
```

You can also run it in a `tmux` or `screen` session. If the machine sleeps or reboots, start
the same command again and it resumes.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No credentials. Run xsweeper auth or set OAuth 1.0a keys` | Run `python -m xsweeper auth`, or fill in all four OAuth 1.0a keys in `.env`. Run from the repo folder. |
| `Set X_CLIENT_ID ...` during `auth` | Add the OAuth 2.0 Client ID to `.env`. |
| Browser shows a callback or redirect error | The callback URI in the app settings must match `http://127.0.0.1:8765/callback` exactly (or your `--port` / `X_REDIRECT_URI`). |
| `Authorization failed: state mismatch` | Start `auth` again and use the newest URL it prints. |
| `Auth error 401` | The token has expired or was revoked. Run `auth` again, or regenerate the OAuth 1.0a tokens. |
| `Auth error 403` | The app isn't **Read and write**, or the OAuth 1.0a token was made before you changed that. Regenerate it. It can also mean the plan doesn't allow this endpoint, or credits ran out (`payg`). |
| `429 rate limited: sleeping ...` | Normal. It waits for the reset. |
| `reset in N min > max wait; stopping` | Raise `--max-wait`, or let the scheduler run it again later. |
| `Daily cap N reached` | Normal on `free` and `basic`. The next day's run continues. |
| Lots of `skipped` | Those posts were already deleted. That's fine. |
| `Matched: 0` | Check `--types` spelling, the date formats, and that the path points to the archive. |
| Port 8765 is already in use | `python -m xsweeper auth --port 9000` and register that callback. |

Failed posts are listed here:
`sqlite3 xsweeper_state.sqlite "SELECT id, detail FROM posts WHERE status='failed';"`

## Safety notes

- **Always do a dry run first.** Deleted posts cannot be recovered.
- Keep the original archive. It is your only copy of what you deleted.
- Use `--exclude` keywords or a reviewed `--ids` CSV to protect posts you want to keep.
- Start small with `--limit 10 --confirm`, then check your profile.
- Like counts come from the archive snapshot, not live data.
- Keep `.env` and `.xsweeper_token.json` private. Revoke the app in X settings when you're done.
- On `payg`, set `--budget`. You pay X directly for API usage.
- The tool uses only the official API, at or below the documented limits. It has no browser
  automation and does no scraping, and none will be added.
- You are responsible for following the X Developer Agreement and Policy. This project is not
  affiliated with or endorsed by X Corp.

## Tests

```bash
pip install pytest
pytest -q
```

The unit tests use a mocked API and a synthetic fixture archive. No real data is included.

## License

MIT License, © 2026 S. Cox. See [LICENSE](LICENSE). Provided as-is, with no warranty.
