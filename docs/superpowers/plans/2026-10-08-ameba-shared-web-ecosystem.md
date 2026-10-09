# AMEBA Shared Web Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive AMEBA website with Telegram and Google sign-in: Telegram users retain existing purchases/progress, while Google users get a separate web profile, without changing or deploying the main bot.

**Architecture:** Keep the current `aiohttp` and static frontend stack. Add a web-only process with server-validated Telegram Login Widget and Google Identity Services. Telegram identity maps to the existing Telegram ID and legacy data; Google identity is keyed by stable `sub` and stored only in web-owned tables ignored by the bot. Develop against an isolated staging database with synthetic fixtures; never connect development or staging to the production volume.

**Tech Stack:** Python 3.12, `aiohttp`, SQLite, `google-auth==2.60.0`, HTML, CSS, vanilla JavaScript, Python `unittest` and `aiohttp.test_utils`.

**Spec:** `docs/superpowers/specs/2026-10-07-web-app-migration-design.md`

## Global Constraints

- Users can use the website directly on phones and computers.
- The main bot's source, commands, behavior, database, and deployment are not changed in this phase.
- Telegram Login Widget data is validated server-side; a client-supplied Telegram ID is never accepted as identity.
- The verified Telegram ID remains the account key used by existing `users`, `purchases`, `question_history`, `trials`, and `sessions` rows.
- Google identity uses verified ID-token `sub`, never email, as its stable key. Google-only profile and progress records use web-owned tables; never insert them into bot-owned user/learning tables.
- Telegram referral/points/access state continues to use the legacy tables; Google-only referral/points/access state remains web-owned.
- The login screen clearly tells users with an existing bot purchase to choose Telegram. Google accounts do not inherit Telegram purchases/history; provider linking is out of scope.
- Do not merge Telegram and Google profiles automatically by email or username.
- Keep provider-specific storage behind account/domain services so later verified account linking can be added without changing the current login contracts.
- Development and staging use a separate database and volume with synthetic account and purchase fixtures only.
- Production integration and any staging deployment require a separate explicit decision; never mount or select the production volume during implementation.
- Telegram domain configuration in BotFather is not performed by implementation code or without the user's control.
- Keep Python `aiohttp` and the existing static frontend stack.
- Payments are not implemented; existing purchase/access records remain authoritative.
- Keep secrets in environment/deployment secrets, never source fallbacks; do not expose the main bot token in logs or browser code.
- Enforce administrator roles on every admin API using a server-side allowlist of Telegram IDs.

## Review Focus

- Tampered or stale Telegram Login Widget payloads must not create sessions; test `test_login_rejects_invalid_hash_and_stale_auth_date` in Task 2.
- Invalid Google ID tokens or GIS CSRF values must not create profiles/sessions; test `test_google_login_rejects_invalid_token_or_csrf` in Task 2.
- Existing access for a verified Telegram ID must be returned without duplicate purchase rows; test `test_verified_telegram_id_uses_existing_purchase` in Task 4.
- Google sign-in must create web-owned records only and must not create bot-visible users, purchases, or history; test `test_google_profile_isolated_from_telegram_tables` in Task 4.
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
- `WebSettings.from_env() -> WebSettings` requires `AMEBA_WEB_DB_PATH`, `AMEBA_WEB_SESSION_SECRET`, `AMEBA_TELEGRAM_LOGIN_BOT_TOKEN`, `AMEBA_TELEGRAM_LOGIN_BOT_USERNAME`, and `AMEBA_GOOGLE_CLIENT_ID`; the username is public and used by Telegram Login Widget, while the token remains server-only. Reads `AMEBA_WEB_ENV` (`local` or `staging`), `AMEBA_WEB_SESSION_TTL_SECONDS` (default `2592000`), `AMEBA_WEB_ADMIN_IDS`, `AMEBA_WEB_BASE_URL`, `AMEBA_WEB_HOST`/`AMEBA_WEB_PORT`, and staging gate credentials. In staging, both gate credentials are mandatory.
- `init_web_database(db_path: str) -> None` creates the existing bot-compatible question, user, purchase, history, trial, referral, points, and session schema idempotently, plus web-owned Google profile/history/session/access tables. It never imports `init_db.py`; the bot never queries the new web-owned tables.
- Preserve `create_app(bot) -> web.Application`; add `create_web_app(settings: WebSettings) -> web.Application` for the standalone web process. The standalone app stores `app["db_path"]` explicitly, and all web DB access uses that path.
- `web_main.py` imports only the web entry point; it never imports `main.py`, creates a Telegram bot, or starts polling.
- Legacy Telegram Mini App auth keeps its existing behavior in `create_app(bot)`. Web-only browser auth is cookie-backed and process database path is explicit.

- [ ] **Step 1: Add `test_web_settings_require_explicit_isolated_configuration`** for required isolated DB path, session secret, both provider configuration values, defaults, malformed port, and incomplete staging gate credentials.
- [ ] **Step 2: Run settings tests** with `python -m unittest tests.test_webapp_settings -v`; confirm they fail because the settings module is absent.
- [ ] **Step 3: Implement `WebSettings.from_env()`** with no database-path or secret fallback.
- [ ] **Step 4: Add runtime tests** proving the standalone app serves from a temporary configured DB, does not import `main`, and rejects requests missing staging Basic credentials.
- [ ] **Step 5: Implement the compatible staging schema, `create_web_app()`, and `web_main.py`**; ensure standalone startup cannot select `/data/questions.db` implicitly and defer legacy `config` imports to the bot-only path. Keep web-only dependencies out of the bot requirement set.
- [ ] **Step 6: Run focused runtime tests** and confirm the bot factory remains callable with existing behavior.
- [ ] **Step 7: Commit** as `feat: add isolated web runtime`.

### Task 2: Verified Telegram/Google Login and Web Sessions

**Files:**
- Create: `webapp_sessions.py`
- Create: `webapp_google_auth.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Test: `tests/test_telegram_login.py`
- Test: `tests/test_google_login.py`
- Test: `tests/test_webapp_session_api.py`

**Interfaces:**
- `TelegramIdentity` is an immutable record with `user_id: int`, `first_name: str`, `username: str | None`, and `photo_url: str | None`.
- `validate_telegram_login(data: Mapping[str, str], bot_token: str, now: int, max_age_seconds: int = 300) -> TelegramIdentity | None` validates Telegram's Login Widget HMAC and auth date.
- `GoogleIdentity` is an immutable record with `subject: str`, `email: str | None`, `display_name: str | None`, and `picture: str | None`.
- `validate_google_id_token(token: str, client_id: str) -> GoogleIdentity | None` uses `google.oauth2.id_token.verify_oauth2_token`; only `sub` is the stable identity. Reject invalid signature, audience, issuer, or expiry.
- `WebIdentity` is an immutable record with `provider: Literal["telegram", "google"]`, `account_key: str`, `display_name: str`, and `is_admin: bool`.
- `create_session(db_path: str, identity: WebIdentity, secret: bytes, ttl_seconds: int) -> str` stores only a hash of a random token plus provider/account key in the web-owned `web_sessions` table.
- `resolve_session(db_path: str, token: str, secret: bytes, now: int) -> WebIdentity | None` returns the provider and account key for a valid session; rejects missing, revoked, or expired sessions.
- `POST /api/session/telegram` accepts the signed widget payload, upserts only profile metadata in `users` keyed by verified Telegram ID, then sets an `HttpOnly`, `SameSite=Lax` cookie (`Secure` on HTTPS).
- `POST /api/session/google` accepts GIS form fields `credential` and `g_csrf_token`, verifies the double-submit cookie/body token, verifies the Google ID token, creates/updates only a web-owned Google profile, then sets the same protected session cookie.
- `GET /api/session` returns the authenticated ID and profile; `POST /api/session/logout` revokes the server session and clears the cookie.
- Server-side admin role derives only from a verified Telegram ID in `AMEBA_WEB_ADMIN_IDS`; Google identities are never admins by profile data or request JSON.
- Cookie-authenticated state-changing routes reject cross-origin `Origin` values, except the Google login callback, which validates GIS's double-submit CSRF cookie/body token.

- [ ] **Step 1: Add `test_login_rejects_invalid_hash_and_stale_auth_date`** plus Telegram tests for valid payloads, tampered fields, missing hash, malformed IDs, and stale/future `auth_date`.
- [ ] **Step 2: Add `test_google_login_rejects_invalid_token_or_csrf`** plus Google tests for invalid signature, audience/issuer/expiry, missing `sub`, and email changes not changing identity.
- [ ] **Step 3: Run `python -m unittest tests.test_telegram_login tests.test_google_login -v`** and confirm tests fail because the validators are absent.
- [ ] **Step 4: Implement both validators** with Telegram's documented constant-time HMAC check and Google's official `google-auth` verifier; run Google key-fetch verification in `asyncio.to_thread` and validate GIS CSRF using the double-submit cookie pattern.
- [ ] **Step 5: Add session/API tests** for both logins, session restore, logout, cookie flags, expiration, existing Telegram user preservation, Google-table isolation, cross-origin mutation rejection, and the verified GIS callback exception.
- [ ] **Step 6: Implement provider-tagged hashed sessions and login routes**; Telegram login never resets purchases/history, Google login never writes legacy Telegram user/purchase/history rows.
- [ ] **Step 7: Run focused auth/session modules** and verify invalid provider credentials never create profiles or sessions.
- [ ] **Step 8: Commit** as `feat: add Telegram and Google web auth`.

### Task 3: Browser-Native Responsive Client

**Files:**
- Create: `web_static/index.html`
- Create: `web_static/app.js`
- Create: `web_static/style.css`
- Test: `tests/test_web_client_contract.py`

**Interfaces:**
- Login screen offers Telegram and Google buttons. A persistent note tells users with an existing Telegram purchase to choose Telegram; it explains Google starts a separate web account.
- Telegram Login Widget posts its auth payload to `/api/session/telegram`; Google GIS posts its credential/CSRF fields to `/api/session/google`; both then use the session cookie.
- Client calls `GET /api/session` on startup and renders login when unauthenticated.
- Browser navigation uses History API; no `Telegram.WebApp`, Mini App `initData`, or Telegram `Authorization` header.
- The standalone web client receives the public Google client ID and Telegram bot username from server config; no provider secret or bot token enters HTML/JavaScript. Its `web_static/` bundle is separate from the Telegram Mini App's existing `static/` bundle.

- [ ] **Step 1: Add browser contract tests** for both provider buttons and the Telegram-purchase reminder; permit both provider libraries but reject Telegram Web App APIs and authorization headers.
- [ ] **Step 2: Run `python -m unittest tests.test_web_client_contract -v`** and confirm the current Mini App shell fails the contract.
- [ ] **Step 3: Replace Mini App initialization with dual-provider sign-in and session restoration** using the Task 2 endpoints.
- [ ] **Step 4: Replace Telegram BackButton with browser history** while retaining direct URLs for learning routes.
- [ ] **Step 5: Make responsive viewport/style changes** without disabling user zoom; ensure desktop and phone navigation layouts.
- [ ] **Step 6: Run contract tests and inspect login, refresh, and browser-back flows** at phone and desktop viewports.
- [ ] **Step 7: Commit** as `feat: make the learning client browser-native`.

### Task 4: Learning and Existing Purchase Entitlements

**Files:**
- Modify: `webapp_server.py`
- Modify: `webapp_schema.py`
- Modify: `web_static/app.js`
- Test: `tests/test_web_learning_api.py`

**Interfaces:**
- Web handlers resolve a provider-tagged identity; Telegram sessions use the verified legacy Telegram `user_id`, Google sessions use `sub` in web-owned learning tables. User IDs supplied in requests are ignored for ownership.
- Existing `/api/config`, `/api/access`, `/api/exam/*`, `/api/test/*`, and `/api/review` flows remain available to authenticated web sessions.
- Access checks read the existing `purchases` rows using the verified Telegram ID; the website does not create replacement purchase records.
- Telegram trial/history/session writes use the same schema and ID as the bot. Google trial/history/session writes use web-owned tables the bot never queries.
- Google users have no inherited purchase rows; web-admin grants for Google are stored only as web entitlements.
- Purchase/checkout routes remain unavailable in standalone web mode; do not alter purchase behavior in bot mode.

- [ ] **Step 1: Add `test_verified_telegram_id_uses_existing_purchase`, `test_google_profile_isolated_from_telegram_tables`, and `test_learning_data_is_scoped_to_verified_telegram_id`** plus API tests for Google no-purchase defaults, Google learning persistence in web-owned tables, catalog/config, practice, exam, review, missing sessions, and attempted cross-account ID injection.
- [ ] **Step 2: Run `python -m unittest tests.test_web_learning_api -v`** and confirm web requests currently fail without a cookie session.
- [ ] **Step 3: Adapt web request authentication** so standalone routes resolve the session cookie while bot-mode requests retain current Mini App auth.
- [ ] **Step 4: Add isolated DB path support to web handlers** without changing `main.py` or accessing the production DB.
- [ ] **Step 5: Complete provider-aware learning route behavior and client calls**; prove Telegram sees existing access with no duplicate grants and Google stays outside legacy Telegram tables.
- [ ] **Step 6: Run focused API tests** across two Telegram IDs and two Google subjects; verify isolation and no implicit provider linking.
- [ ] **Step 7: Commit** as `feat: share learning state by Telegram account`.

### Task 5: Web Support, Referrals, and Administrator Workflows

**Files:**
- Create: `webapp_operations.py`
- Create: `referral_domain.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Create: `web_static/admin.html`
- Create: `web_static/admin.js`
- Create: `web_static/admin.css`
- Modify: `web_static/app.js`
- Test: `tests/test_web_operations.py`
- Test: `tests/test_web_admin_api.py`
- Test: `tests/test_web_admin_client_contract.py`
- Test: `tests/test_referral_domain.py`

**Interfaces:**
- User web services cover support tickets/replies, announcements, promo, referrals, and non-purchase points.
- Admin APIs cover question search/edit/delete, statistics, support replies, announcements, promo, account lookup, and manual access grant/revoke.
- Every admin handler calls a shared `require_admin(request)` that derives the user's Telegram ID from the validated web session and compares it with `AMEBA_WEB_ADMIN_IDS`.
- Telegram referrals, points, and access continue to use the legacy tables keyed by verified Telegram ID, so bot and site see the same state. Google-only referrals, points, support, and web grants use web-owned tables keyed by provider and stable subject; Google entitlements never use the legacy `purchases` table.
- The existing bot's referral code and `main.py` are not modified. Web-specific services may share pure referral rules only when extracted without changing bot callers; otherwise preserve behavior and duplicate only the minimal tested rule.

- [x] **Step 1: Add `test_non_admin_cannot_call_admin_api` and `test_telegram_referral_state_uses_legacy_tables`** plus tests for support ownership/replies for both providers, notice visibility, promo updates, referral linking/points, Telegram access, Google web-only grants, and admin access.
- [x] **Step 2: Add admin client contract tests** asserting no static password token or Telegram Web App auth remains.
- [x] **Step 3: Run the focused operations/admin/referral tests** and confirm new routes are absent or deny unauthenticated requests.
- [x] **Step 4: Add isolated web operation tables and implement support, announcements, promo, referral, and points services** in web-owned modules.
- [x] **Step 5: Implement server-side admin authorization and admin APIs** for questions, statistics, tickets, content, accounts, and manual access.
- [x] **Step 6: Replace the static-password admin browser flow** with the verified session and render the approved admin workflows.
- [x] **Step 7: Run the complete operations/admin suite**; verify regular users cannot escalate and support content is visible only to its owner/admin.
- [x] **Step 8: Commit** as `feat: add web support and admin workflows`.

### Task 6: Isolated Staging Seed and Acceptance

**Files:**
- Create: `Dockerfile.web`
- Create: `fly.staging.toml`
- Create: `Dockerfile.web.dockerignore`
- Create: `requirements.web.txt`
- Create: `scripts/seed_web_staging.py`
- Modify: `web_main.py`
- Test: `tests/test_web_staging_seed.py`
- Test: `tests/test_web_release_smoke.py`

**Interfaces:**
- Staging config uses a distinct app and volume, explicit `AMEBA_WEB_DB_PATH`, staging-only secrets, and an optional outer HTTP Basic gate.
- Seed copies only question rows and creates synthetic Telegram IDs/purchases plus synthetic Google subjects and web-only profiles/progress; it never copies production user, purchase, session, referral, points, or history records.
- Web image starts `web_main.py` only; it does not start `main.py`, Telegram polling, or `init_db.py`.

- [x] **Step 1: Add seed tests** proving only question catalog rows are copied and synthetic user/purchase fixtures are created.
- [x] **Step 2: Run `python -m unittest tests.test_web_staging_seed -v`** and confirm the tests fail because the seed utility is absent.
- [x] **Step 3: Implement the staging seed utility** with a temporary source/destination DB test; no production DB path is accepted as a destination.
- [x] **Step 4: Add web-only Docker/Fly staging files** with distinct app/volume identifiers and explicit secret names; exclude DBs and secret files from image context.
- [x] **Step 5: Add release smoke tests** for both auth contracts, Telegram existing access, Google isolated profile, catalog, practice, exam, review, support, referrals, and admin question management.
- [x] **Step 6: Run `python -m unittest discover -s tests -v`** and verify all tests pass.
- [x] **Step 7: Prepare staging deployment instructions only.** Before any remote deployment or BotFather domain change, obtain the staging app/domain and explicit confirmation; verify production app and volume are not referenced.
- [x] **Step 8: Commit** as `chore: prepare isolated web staging`.
