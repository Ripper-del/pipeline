# Pipeline: Telegram and WhatsApp UBT Automation Suite

![Tests](https://github.com/Ripper-del/pipeline/actions/workflows/tests.yml/badge.svg)

Traffic automation (UBT) tooling for Telegram and WhatsApp, plus a media uniqueization service for TikTok creatives.

## Architecture

Four independent services, each in its own directory:

1. **uniqreo** - the project's only Telegram bot process (single `bot_token`; Telegram does not allow two processes to poll updates on the same token simultaneously). Handles photo/video uniqueization (Pillow and FFmpeg) with automatic TikTok upload, `/upload`, the `/start` lead funnel with smartlink redirection and a SQLite-backed 24h/48h follow-up queue, and the ops-group control panel (warmup/spy/stats/autoupload).
2. **whatsapp-redirect-bot** - the equivalent lead funnel for WhatsApp via Green-API (a separate process, since it is not a Telegram client).
3. **s2s-postback-server** - FastAPI server accepting postbacks from affiliate networks (e.g. iMonetizeIt) and forwarding conversion notifications to Telegram.
4. **tiktok_scraper** - command-line utilities for TikTok keyword search, account warmup/spy, and AdsPower-driven upload. Shared AdsPower/captcha/human-input/Telegram-notification code lives in `tiktok_scraper/common/` and is reused by `uniqreo/uploader.py`.

## Directory structure

```
pipeline/
├── docker-compose.yml           # Full-stack Docker Compose configuration
├── requirements.txt             # Consolidated dependencies for local (non-Docker) runs
├── requirements-dev.txt         # + pytest, for running the test suite
├── conftest.py                  # sys.path setup for tests (modules live in separate directories)
├── .env.example                 # Environment configuration template
├── .gitignore
├── .dockerignore                # Docker build-context excludes (root context is required by uniqreo)
├── .github/workflows/tests.yml  # CI: pytest + py_compile on every push/PR
├── tests/                       # Unit tests (see "Testing")
│
├── uniqreo/                     # The project's only Telegram bot process
│   ├── bot.py                   # Uniqueization, /upload, lead funnel, control panel
│   ├── uploader.py              # TikTok upload module (uses tiktok_scraper/common)
│   ├── Dockerfile               # Built from the repo root (needs access to tiktok_scraper/)
│   ├── requirements.txt
│   └── core/
│       ├── config.py
│       ├── photo_processor.py
│       └── video_processor.py
│
├── tiktok_scraper/              # TikTok scraping and automation
│   ├── common/                  # Shared AdsPower, captcha, human-typing, Telegram-notify code
│   │   ├── adspower.py
│   │   ├── captcha.py
│   │   ├── human_input.py
│   │   └── telegram_notify.py
│   ├── scraper.py               # Search/profile scraper CLI
│   ├── automator.py             # Warmup/spy via AdsPower (also launched as a subprocess by uniqreo/bot.py)
│   ├── uploader.py              # AdsPower upload CLI
│   └── requirements.txt
│
├── whatsapp-redirect-bot/       # WhatsApp lead funnel (Green-API)
│   ├── bot.py
│   ├── Dockerfile
│   └── requirements.txt
│
└── s2s-postback-server/         # FastAPI S2S postback receiver
    ├── server.py
    ├── Dockerfile
    └── requirements.txt
```

## Environment configuration (.env)

```bash
cp .env.example .env
```

### Variables

* `API_ID`, `API_HASH` - Telegram application credentials from https://my.telegram.org. Used by `uniqreo`, the project's only Telegram bot.
* `REDIRECT_BOT_TOKEN` - the single Telegram bot token, used for uniqueization/`/upload`, the `/start` lead funnel, and the control panel. There is no separate redirect-bot token.
* `SOURCE_THREAD_ID`, `TARGET_THREAD_ID` - forum thread IDs for automatic media uniqueization (raw creatives in, clean creatives out).
* `ADMIN_TELEGRAM_IDS` - comma-separated Telegram user IDs allowed to run `/upload` (drives a real AdsPower browser). Empty by default; the command is rejected for everyone until explicitly configured.
* `SMARTLINK_URL` - base redirect link.
* `S2S_POSTBACK_SECRET` - shared secret the affiliate network must send as `?secret=...` on `/postback`. Without it the server rejects all postbacks with 403; generate a random value and add it to the postback URL in the affiliate dashboard.
* `LEAD_CHAT_ID`, `LEAD_THREAD_ID` - chat/thread the S2S server posts lead notifications and the daily report to.
* `DAILY_REPORT_HOUR_UTC` - UTC hour (0-23) at which `s2s-postback-server` posts the daily lead summary (default `21`).
* `LOG_CHAT_ID` - chat for automation logs (falls back to `LEAD_CHAT_ID` if unset).
* `WARMUP_THREAD_ID` - thread for warmup logs and control-panel buttons.
* `SPY_THREAD_ID` - thread for spy-mode logs and control-panel buttons.
* `UPLOAD_THREAD_ID` - thread for uniqueization/upload progress logs and the autoupload button.
* `S2S_STATS_URL` - `s2s-postback-server` base URL for the "stats" control-panel button (`http://s2s_server:8000` in Docker Compose).
* `DEFAULT_GEO` - default GEO for warmup/spy runs launched from the control panel (default `US`).
* `GREEN_API_ID_INSTANCE`, `GREEN_API_TOKEN_INSTANCE` - Green-API instance credentials for the WhatsApp bot.
* `GREEN_API_URL` - Green-API base URL (default `https://api.green-api.com`).
* `ADSPOWER_API_URL` - local AdsPower API URL (default `http://localhost:50325`; resolves to `http://host.docker.internal:50325` inside a container).
* `ADSPOWER_PROFILE_ID` / `ADSPOWER_PROFILE_IDS` - single AdsPower profile ID, or a comma-separated list for rotation mode (`ADSPOWER_PROFILE_IDS` takes priority).

## Running

### Docker Compose (recommended)

```bash
docker-compose up --build -d
```

Starts three containers:

1. `uniqreo_bot` - the project's only Telegram bot (uniqueization, `/upload`, lead funnel, control panel)
2. `wa_redirect_bot`
3. `s2s_fastapi` (port 8000)

```bash
docker-compose logs -f [service_name]
```

### Local (without Docker)

1. Install system dependencies (`ffmpeg` is required for `uniqreo`).
2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run services individually:

   **Telegram bot** - `uniqreo/uploader.py` imports the shared `tiktok_scraper/common` package, so outside Docker `tiktok_scraper` must be on `PYTHONPATH`:
   ```bash
   cd uniqreo && PYTHONPATH=../tiktok_scraper python bot.py
   ```

   **WhatsApp bot**:
   ```bash
   cd whatsapp-redirect-bot && python bot.py
   ```

   **S2S server**:
   ```bash
   cd s2s-postback-server && uvicorn server:app --host 0.0.0.0 --port 8000
   ```

   **TikTok scraper** - install Playwright's browser binary once:
   ```bash
   playwright install chromium
   ```
   Search mode:
   ```bash
   python tiktok_scraper/scraper.py -s "crypto" -d "bitcoin,earn" -c "info,interested" -l 10
   ```
   Profile mode (`-s`/`--search` and `-p`/`--profile` are mutually exclusive, exactly one required):
   ```bash
   python tiktok_scraper/scraper.py -p someusername -l 20
   ```
   Parameters:
   - `-s` / `--search` - search query (mutually exclusive with `-p`).
   - `-p` / `--profile` - TikTok username to scrape, without `@` (mutually exclusive with `-s`).
   - `-d` / `--desc-keywords` - comma-separated keywords to filter video descriptions.
   - `-c` / `--comment-keywords` - comma-separated keywords to filter comments.
   - `-l` / `--limit` (default 10) - max videos to analyze.
   - `-o` / `--output` (default `results.json`).
   - `--headless` (default on) - run the browser without a UI.
   - `--resume` - skip videos already present in `--output` from a previous run.
   - `--proxy` - browser proxy, e.g. `http://user:pass@host:port`.

   **TikTok warmup/spy automation (AdsPower)** - AdsPower must be running with its Local API enabled (default port 50325).

   Behavior notes:
   - Mouse movement and scrolling follow a cubic Bezier curve (`ease_in_out`) with added micro-jitter, to avoid behavioral bot detection.
   - 15 GEO/language profiles are built in (US, UK, DE, FR, ES, IT, BR, NL, PL, TR, RO, JP, KR, VN, CA), each with localized dating-niche search queries and casual comment phrasing.
   - Comments are drawn from a local per-GEO phrase dictionary; no external AI service is used.

   Two modes:
   1. `warmup` - searches dating-niche content, watches videos for 6-15s, likes and comments, to train TikTok's recommendation algorithm toward the dating/adult-dating niche.
   2. `spy` - monitors the feed/search and likes/comments on every 5th matching video.

   ```bash
   python tiktok_scraper/automator.py --mode warmup --geo US --profile-id "PROFILE_ID"
   python tiktok_scraper/automator.py --mode spy --geo DE --profile-id "PROFILE_ID"
   ```

   Profile rotation - process a comma-separated list of profiles sequentially with a random delay between them (disguises batch processing as independent sessions). If one profile errors, the rest continue; a non-zero exit code only occurs if all profiles fail:
   ```bash
   python tiktok_scraper/automator.py --mode warmup --geo US --profile-ids "profile1,profile2,profile3" --profile-delay-min 30 --profile-delay-max 90
   ```
   The profile list can also be set via `ADSPOWER_PROFILE_IDS` in `.env` instead of `--profile-ids`.

   Parameters:
   - `--mode` (required) - `warmup` or `spy`.
   - `--profile-id` - single AdsPower profile ID; falls back to `.env` (`ADSPOWER_PROFILE_ID`) or a local Chromium instance if unset.
   - `--profile-ids` - comma-separated profile IDs for rotation mode; takes priority over `--profile-id`.
   - `--profile-delay-min` / `--profile-delay-max` (default 30/90) - random inter-profile delay range in rotation mode.
   - `--geo` (default `US`) - one of the 15 supported GEOs.
   - `--limit` (default 15) - video processing limit.
   - `--api-url` (default `http://localhost:50325`) - local AdsPower API URL.
   - `--headless` - run a local (non-AdsPower) browser headless.

   **Automated creative upload (via the Telegram bot)** - send `/upload <profile_id> [caption]` to the bot, either as a video caption or as a reply to a video message. The bot downloads the video, uniqueizes it, launches the given AdsPower profile via CDP, and uploads to TikTok with simulated text entry. Concurrent uploads are capped at 2. Restricted to `ADMIN_TELEGRAM_IDS`; empty by default, so unreachable until configured.

   Manual CLI equivalent:
   ```bash
   python tiktok_scraper/uploader.py --video "path/to/video.mp4" --profile-id "PROFILE_ID" --caption "Caption and hashtags"
   ```

   Multi-profile upload via one button - instead of running `/upload <profile_id>` once per profile, each `ADMIN_TELEGRAM_IDS` user can bind a list of AdsPower profiles to themselves and upload one video to all of them with a single tap of "Autoupload" in the `UPLOAD_THREAD_ID` thread (see "Control panel" below):
   - `/addprofile <profile_id>` - bind a profile.
   - `/removeprofile <profile_id>` - unbind a profile.
   - `/myprofiles` - list bound profiles.

   Bindings are stored per Telegram user ID in SQLite, so different operators in the same group see and upload to only their own profiles.

## Telegram integration: per-thread logging

Reports and notifications are routed to separate forum threads:
- Leads and conversions (from the S2S server) go to `LEAD_THREAD_ID`.
- Warmup logs go to `WARMUP_THREAD_ID`.
- Spy-mode logs go to `SPY_THREAD_ID`.
- Upload logs go to `UPLOAD_THREAD_ID`.

`WARMUP_THREAD_ID` and `SPY_THREAD_ID` may point at the same thread (the default in `.env.example`), putting both modes' logs and control buttons in one place. Set them to different values to split the two.

## Lead persistence and daily report

`s2s-postback-server` persists every accepted postback (after secret validation) to SQLite (`data/leads.db`) - amount, GEO, status (charged/held), timestamp. In addition to the per-conversion notification, a 24-hour summary (lead count, charged total, held total) is posted to `LEAD_CHAT_ID`/`LEAD_THREAD_ID` once a day, whether or not there were any leads - this also serves as a liveness signal for the pipeline. Report time is set via `DAILY_REPORT_HOUR_UTC` (UTC hour, default `21`).

## Control panel (per-thread reply buttons)

At startup, `uniqreo` sends a reply-keyboard to each configured ops-group thread. Reply keyboards are scoped to the thread they were sent in - forum topics are visually separate windows with separate compose areas.

- `LEAD_THREAD_ID`: "Stats" - calls `/stats` on `s2s-postback-server` (same `S2S_POSTBACK_SECRET`, address in `S2S_STATS_URL`) for an on-demand summary.
- `WARMUP_THREAD_ID`: "Start warmup" / "Stop warmup" - launches/terminates `automator.py --mode warmup` as a subprocess, using `.env` parameters (`ADSPOWER_PROFILE_IDS`/`ADSPOWER_PROFILE_ID`, `DEFAULT_GEO`). Progress is logged to the same thread by `automator.py` itself.
- `SPY_THREAD_ID`: same, for `spy` mode.
- `UPLOAD_THREAD_ID`: "Autoupload" - an operator drops a video in this thread (optionally with a caption in place of `[description]`), the bot confirms receipt, and the button uploads that video to every AdsPower profile the operator has bound via `/addprofile`. Bound profile management: `/addprofile <profile_id>`, `/removeprofile <profile_id>`, `/myprofiles`. Restricted to `ADMIN_TELEGRAM_IDS`, same as `/upload`; bindings are per-user.
- `SOURCE_THREAD_ID`, `TARGET_THREAD_ID`: no buttons - these are media streams for automatic uniqueization, not command threads.

If `WARMUP_THREAD_ID` and `SPY_THREAD_ID` point at the same thread, that thread gets one keyboard with all four buttons (two rows: warmup start/stop, spy start/stop) - `resolve_thread_button_map` in `uniqreo/bot.py` merges rows by thread ID instead of one overwriting the other.

Pressing "Start" while a run is already active is a no-op (replies that it's already running); "Stop" with nothing active replies that there is nothing to stop.

Known limitations:
- Running-job state lives only in the `uniqreo` process's memory - a container restart loses track of an in-flight subprocess (the subprocess itself dies with the container).
- Buttons launch runs with default `.env` parameters; there is no live GEO/profile selection dialog.
- "Autoupload" likewise holds the last-dropped-video-per-user mapping only in memory - if the container restarts between sending the video and pressing the button, the video must be resent.

## How message reception works

`uniqreo/bot.py` uses `pyrofork` (a pyrogram fork) for outbound Telegram API calls - sending messages, documents, and downloading media all go over its MTProto connection. Incoming updates are handled differently: the `Client` is started with `no_updates=True`, and a separate loop (`get_updates_loop`/`dispatch_update` in `bot.py`) polls the classic Bot API's `getUpdates` endpoint directly and routes each message to the matching handler.

This split exists because, in this deployment's network conditions, pyrogram's direct MTProto connection reliably sends but does not reliably receive push updates, while the classic Bot API's `getUpdates` - a stateless request/response call - tolerates connection instability far better than a long-lived push socket. `download`/`send_document` calls are wrapped with a hard timeout and automatic retry (`_with_hard_timeout`/`_with_retries` in `bot.py`), since a stalled transfer on this network can otherwise hang indefinitely rather than raising an error.

## Follow-up funnel

1. On first contact with the Telegram or WhatsApp bot, a personal link is generated: `{SMARTLINK_URL}{user_id}`, where `user_id` is the Telegram ID or WhatsApp phone number.
2. The bot sends a welcome message containing that link.
3. A follow-up task is scheduled in the background:
   - First reminder after 24 hours.
   - Final reminder after 48 hours.
4. Follow-up delivery is asynchronous and does not block new message handling.

## Dependency versions

All `requirements.txt` files pin versions (`~=` for patch-level flexibility, `playwright==` exactly). Playwright is pinned exactly because the Python package version must match the downloaded browser binary - after upgrading playwright, re-run `playwright install chromium`.

## Healthcheck and logging

- `s2s-postback-server` exposes `GET /health` (no side effects, does not touch Telegram) for the Docker healthcheck.
- The other two long-running services (`uniqreo`, `whatsapp-redirect-bot`) write a heartbeat file every 30 seconds; if it goes stale for more than 90 seconds, `docker ps` reports the container as `unhealthy` - this catches a hung (not crashed) process, which `restart: unless-stopped` alone would not notice.
- All services use the `logging` module instead of `print()`, with timestamps and levels (`INFO`/`WARNING`/`ERROR`), filterable via `docker-compose logs -f [service_name]`.

## Testing

Unit tests (pytest) cover logic that does not require network or browser access: TikTok API response parsing, deduplication, captcha detection, human-typing, `ADMIN_TELEGRAM_IDS` parsing, `s2s-postback-server` endpoints, the `uniqreo` control panel and profile bindings.

```bash
pip install -r requirements-dev.txt
pytest -v
```

CI (`.github/workflows/tests.yml`) runs the same suite plus `py_compile` across all files on every push/PR to `main`/`dev`.
