# AMEBA Shared Web Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive AMEBA website that authenticates users through Telegram and shares their existing account identity, purchases, and learning progress with the bot, without changing or deploying the main bot.

**Architecture:** Keep the current `aiohttp` and static frontend stack. Add a web-only process, validate Telegram Login Widget signatures server-side, and use the verified Telegram ID with the existing schema. Develop against an isolated staging database containing the question catalog and synthetic users/purchases; never connect development or staging to the production volume.

**Tech Stack:** Python 3.12, `aiohttp`, SQLite, HTML, CSS, vanilla JavaScript, Python `unittest` and `aiohttp.test_utils`.

**Spec:** `docs/superpowers/specs/2026-10-07-web-app-migration-design.md`

## Global Constraints

- Users can use the website directly on phones and computers.
- The main bot's source, commands, behavior, database, and deployment are not changed in this phase.
- Telegram Login Widget data is validated server-side; a client-supplied Telegram ID is never accepted as identity.
- The verified Telegram ID remains the account key used by existing `users`, `purchases`, `question_history`, `trials`, and `sessions` rows.
- Development and staging use a separate database and volume with synthetic account and purchase fixtures only.
- Production integration and any staging deployment require a separate explicit decision; never mount or select the production volume during implementation.
- Telegram domain configuration in BotFather is not performed by implementation code or without the user's control.
- Keep Python `aiohttp` and the existing static frontend stack.
- Payments are not implemented; existing purchase/access records remain authoritative.
- Keep secrets in environment/deployment secrets, never source fallbacks; do not expose the main bot token in logs or browser code.
- Enforce administrator roles on every admin API using a server-side allowlist of Telegram IDs.

## Review Focus

- Tampered or stale Telegram Login Widget payloads must not create sessions; test `test_login_rejects_invalid_hash_and_stale_auth_date` in Task 2.
- Existing access for a verified Telegram ID must be returned without duplicate purchase rows; test `test_verified_telegram_id_uses_existing_purchase` in Task 4.
- User A must not read or mutate User B's learning state by changing request IDs; test `test_learning_data_is_scoped_to_verified_telegram_id` in Task 4.
- A regular account must not gain admin access by altering browser requests; test `test_non_admin_cannot_call_admin_api` in Task 5.
- Missing staging DB path or gate credentials must fail closed rather than fall back to `/data/questions.db`; test `test_web_settings_require_explicit_isolated_configuration` in Task 1.

---

### Task 1: Web-Only Runtime and Compatible Staging Database

**Files:**
- Create: `webapp_settings.py`
- Create: `webapp_schema.py`
- Create: `web_main.py`
- Create: `tests/__init__.py`
- Modify: `webapp_server.py`
- Test: `tests/test_webapp_settings.py`
- Test: `tests/test_webapp_runtime.py`

**Interfaces:**
- `WebSettings.from_env() -> WebSettings` requires `AMEBA_WEB_DB_PATH`, `AMEBA_WEB_SESSION_SECRET`, and `AMEBA_TELEGRAM_LOGIN_BOT_TOKEN`; reads `AMEBA_WEB_ENV` (`local` or `staging`), `AMEBA_WEB_SESSION_TTL_SECONDS` (default `2592000`), `AMEBA_WEB_ADMIN_IDS`, `AMEBA_WEB_BASE_URL`, `AMEBA_WEB_HOST`/`AMEBA_WEB_PORT`, and staging gate credentials. In staging, both gate credentials are mandatory.
- `init_web_database(db_path: str) -> None` creates the existing bot-compatible question, user, purchase, history, trial, referral, points, and session schema idempotently; web-session and web-operation tables are added by their owning tasks. It never imports `init_db.py`.
- Preserve `create_app(bot) -> web.Application`; add `create_web_app(settings: WebSettings) -> web.Application` for the standalone web process. The standalone app stores `app["db_path"]` explicitly, and all web DB access uses that path.
- `web_main.py` imports only the web entry point; it never imports `main.py`, creates a Telegram bot, or starts polling.
- Legacy Telegram Mini App auth keeps its existing behavior in `create_app(bot)`. Web-only browser auth is cookie-backed and process database path is explicit.

- [ ] **Step 1: Add settings tests** for required isolated DB path, session secret, login-widget bot token, defaults, malformed port, and incomplete staging gate credentials.
- [ ] **Step 2: Run settings tests** with `python -m unittest tests.test_webapp_settings -v`; confirm they fail because the settings module is absent.
- [ ] **Step 3: Implement `WebSettings.from_env()`** with no database-path or secret fallback.
- [ ] **Step 4: Add runtime tests** proving the standalone app serves from a temporary configured DB, does not import `main`, and rejects requests missing staging Basic credentials.
- [ ] **Step 5: Implement the compatible staging schema, `create_web_app()`, and `web_main.py`**; ensure standalone startup cannot select `/data/questions.db` implicitly and defer legacy `config` imports to the bot-only path.
- [ ] **Step 6: Run focused runtime tests** and confirm the bot factory remains callable with existing behavior.
- [ ] **Step 7: Commit** as `feat: add isolated web runtime`.

### Task 2: Verified Telegram Login and Web Sessions

**Files:**
- Create: `webapp_sessions.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Test: `tests/test_telegram_login.py`
- Test: `tests/test_webapp_session_api.py`

**Interfaces:**
- `TelegramIdentity` is an immutable record with `user_id: int`, `first_name: str`, `username: str | None`, and `photo_url: str | None`.
- `validate_telegram_login(data: Mapping[str, str], bot_token: str, now: int, max_age_seconds: int = 300) -> TelegramIdentity | None` validates Telegram's Login Widget HMAC and auth date.
- `create_session(db_path: str, account_id: int, secret: bytes, ttl_seconds: int) -> str` stores only a hash of a random token in `web_sessions`.
- `resolve_session(db_path: str, token: str, secret: bytes, now: int) -> TelegramIdentity | None` rejects missing, revoked, or expired sessions.
- `POST /api/session/telegram` accepts the signed widget payload, upserts only profile metadata in `users` keyed by verified Telegram ID, then sets an `HttpOnly`, `SameSite=Lax` cookie (`Secure` on HTTPS).
- `GET /api/session` returns the authenticated ID and profile; `POST /api/session/logout` revokes the server session and clears the cookie.
- Server-side admin role derives from `AMEBA_WEB_ADMIN_IDS`, never from widget profile fields or request JSON.
- Cookie-authenticated state-changing requests reject cross-origin `Origin` values.

- [ ] **Step 1: Add Telegram signature tests** for valid payloads, tampered fields, missing hash, malformed IDs, and stale/future `auth_date`.
- [ ] **Step 2: Run `python -m unittest tests.test_telegram_login -v`** and confirm the tests fail because the validator is absent.
- [ ] **Step 3: Implement `validate_telegram_login()`** using Telegram's documented sorted data-check string and constant-time HMAC comparison.
- [ ] **Step 4: Add session tests** for login, session restore, logout, cookie flags, expiration, existing user preservation, and cross-origin mutation rejection.
- [ ] **Step 5: Implement hashed session storage, session API routes, and same-origin checks for cookie-authenticated mutations**; do not replace or reset existing user, purchase, or progress rows.
- [ ] **Step 6: Run both focused test modules** and verify an invalid signature never creates a user or session.
- [ ] **Step 7: Commit** as `feat: add verified Telegram web sessions`.

### Task 3: Browser-Native Responsive Client

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/style.css`
- Test: `tests/test_web_client_contract.py`

**Interfaces:**
- Telegram Login Widget posts its auth payload to `/api/session/telegram`; subsequent same-origin requests use the session cookie.
- Client calls `GET /api/session` on startup and renders login when unauthenticated.
- Browser navigation uses History API; no `Telegram.WebApp`, Mini App `initData`, or Telegram `Authorization` header.

- [ ] **Step 1: Add browser contract tests** that permit the Login Widget but reject Telegram Web App scripts/APIs and authorization headers.
- [ ] **Step 2: Run `python -m unittest tests.test_web_client_contract -v`** and confirm the current Mini App shell fails the contract.
- [ ] **Step 3: Replace Mini App initialization with Telegram Login Widget and session restoration** using the Task 2 endpoints.
- [ ] **Step 4: Replace Telegram BackButton with browser history** while retaining direct URLs for learning routes.
- [ ] **Step 5: Make responsive viewport/style changes** without disabling user zoom; ensure desktop and phone navigation layouts.
- [ ] **Step 6: Run contract tests and inspect login, refresh, and browser-back flows** at phone and desktop viewports.
- [ ] **Step 7: Commit** as `feat: make the learning client browser-native`.

### Task 4: Learning and Existing Purchase Entitlements

**Files:**
- Modify: `webapp_server.py`
- Modify: `webapp_schema.py`
- Modify: `static/app.js`
- Test: `tests/test_web_learning_api.py`

**Interfaces:**
- Web handlers resolve the session to a verified Telegram `user_id`; they ignore user IDs supplied in request bodies or query parameters for ownership.
- Existing `/api/config`, `/api/access`, `/api/exam/*`, `/api/test/*`, and `/api/review` flows remain available to authenticated web sessions.
- Access checks read the existing `purchases` rows using the verified Telegram ID; the website does not create replacement purchase records.
- Trial/history/session writes use the same schema and account ID as the bot.
- Purchase/checkout routes remain unavailable in standalone web mode; do not alter purchase behavior in bot mode.

- [ ] **Step 1: Add API tests** for catalog/config, access from an existing synthetic purchase, expired access, practice, exam, review, missing session, and attempted cross-account ID injection.
- [ ] **Step 2: Run `python -m unittest tests.test_web_learning_api -v`** and confirm web requests currently fail without a cookie session.
- [ ] **Step 3: Adapt web request authentication** so standalone routes resolve the session cookie while bot-mode requests retain current Mini App auth.
- [ ] **Step 4: Add isolated DB path support to web handlers** without changing `main.py` or accessing the production DB.
- [ ] **Step 5: Complete learning route behavior and client calls**; prove the same Telegram ID sees its existing purchase and history fixture with no duplicate grant.
- [ ] **Step 6: Run focused API tests** including two Telegram IDs and verify complete data separation.
- [ ] **Step 7: Commit** as `feat: share learning state by Telegram account`.

### Task 5: Web Support, Referrals, and Administrator Workflows

**Files:**
- Create: `webapp_operations.py`
- Create: `referral_domain.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Modify: `static/admin.html`
- Modify: `static/admin.js`
- Modify: `static/admin.css`
- Modify: `static/app.js`
- Test: `tests/test_web_operations.py`
- Test: `tests/test_web_admin_api.py`
- Test: `tests/test_web_admin_client_contract.py`
- Test: `tests/test_referral_domain.py`

**Interfaces:**
- User web services cover support tickets/replies, announcements, promo, referrals, and non-purchase points.
- Admin APIs cover question search/edit/delete, statistics, support replies, announcements, promo, account lookup, and manual access grant/revoke.
- Every admin handler calls a shared `require_admin(request)` that derives the user's Telegram ID from the validated web session and compares it with `AMEBA_WEB_ADMIN_IDS`.
- The existing bot's referral code and `main.py` are not modified. Web-specific services may share pure referral rules only when extracted without changing bot callers; otherwise preserve behavior and duplicate only the minimal tested rule.

- [ ] **Step 1: Add tests** for support ownership/replies, notice visibility, promo updates, referral linking/points, access grant/revoke, and non-admin rejection.
- [ ] **Step 2: Add admin client contract tests** asserting no static password token or Telegram Web App auth remains.
- [ ] **Step 3: Run the focused operations/admin/referral tests** and confirm new routes are absent or deny unauthenticated requests.
- [ ] **Step 4: Add isolated web operation tables and implement support, announcements, promo, referral, and points services** in web-owned modules.
- [ ] **Step 5: Implement server-side admin authorization and admin APIs** for questions, statistics, tickets, content, accounts, and manual access.
- [ ] **Step 6: Replace the static-password admin browser flow** with the verified session and render the approved admin workflows.
- [ ] **Step 7: Run the complete operations/admin suite**; verify regular users cannot escalate and support content is visible only to its owner/admin.
- [ ] **Step 8: Commit** as `feat: add web support and admin workflows`.

### Task 6: Isolated Staging Seed and Acceptance

**Files:**
- Create: `Dockerfile.web`
- Create: `fly.staging.toml`
- Create: `.dockerignore`
- Create: `scripts/seed_web_staging.py`
- Modify: `web_main.py`
- Test: `tests/test_web_staging_seed.py`
- Test: `tests/test_web_release_smoke.py`

**Interfaces:**
- Staging config uses a distinct app and volume, explicit `AMEBA_WEB_DB_PATH`, staging-only secrets, and an optional outer HTTP Basic gate.
- Seed copies only question rows and creates synthetic Telegram IDs, users, purchase/access rows, referral fixtures, and histories; it never copies production user, purchase, session, referral, points, or history records.
- Web image starts `web_main.py` only; it does not start `main.py`, Telegram polling, or `init_db.py`.

- [ ] **Step 1: Add seed tests** proving only question catalog rows are copied and synthetic user/purchase fixtures are created.
- [ ] **Step 2: Run `python -m unittest tests.test_web_staging_seed -v`** and confirm the tests fail because the seed utility is absent.
- [ ] **Step 3: Implement the staging seed utility** with a temporary source/destination DB test; no production DB path is accepted as a destination.
- [ ] **Step 4: Add web-only Docker/Fly staging files** with distinct app/volume identifiers and explicit secret names; exclude DBs and secret files from image context.
- [ ] **Step 5: Add release smoke tests** for Telegram auth contract, catalog, access, practice, exam, review, support, referrals, and admin question management.
- [ ] **Step 6: Run `python -m unittest discover -s tests -v`** and verify all tests pass.
- [ ] **Step 7: Prepare staging deployment instructions only.** Before any remote deployment or BotFather domain change, obtain the staging app/domain and explicit confirmation; verify production app and volume are not referenced.
- [ ] **Step 8: Commit** as `chore: prepare isolated web staging`.
