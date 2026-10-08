# AMEBA Web Migration Implementation Plan

> Superseded by `docs/superpowers/plans/2026-10-08-ameba-shared-web-ecosystem.md`; the approved architecture uses verified Telegram identity and preserves existing purchase IDs.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a standalone, responsive AMEBA web application with username-only private staging identity and web equivalents for the bot's user and administrator workflows, while the production bot continues running independently.

**Architecture:** Keep `aiohttp` and the existing HTML/CSS/JavaScript client. Add a web-only process, isolate its database and identity, and remove Telegram Web App dependencies from browser workflows. Build the site in independent increments: runtime and identity, learning, web operations, then private staging acceptance.

**Tech Stack:** Python 3.12, `aiohttp`, SQLite, HTML, CSS, vanilla JavaScript, Python `unittest` and `aiohttp.test_utils`.

**Spec:** `docs/superpowers/specs/2026-10-07-web-app-migration-design.md`

## Global Constraints

- Users must be able to use the web application directly in a browser on both phones and computers.
- The existing Telegram bot remains in production while the web application is developed and validated in isolation.
- Run staging as a separate application with a separate database and storage volume.
- Seed staging with the question catalog and synthetic test accounts; do not copy production personal user records into staging.
- For private staging, a user enters a unique username; the server assigns an immutable internal account ID.
- Username comparison is trimmed and case-insensitive.
- Username-only mode has no proof of account ownership and staging must remain private.
- The web client must not require `window.Telegram`, Telegram `initData`, or a Telegram-specific authorization header.
- Keep Python `aiohttp` and the current static frontend stack for the first migration.
- Payment processing and production authentication are later phases.
- Production release requires a separate explicit decision after authentication and payment phases are complete.
- Store secrets in deployment secrets or environment variables, never as source-code fallbacks.
- Enforce administrator roles on the server for every administrative API.

## Review Focus

- Unicode and case variants of a username must resolve to one profile; pin with `test_username_normalization_is_case_insensitive_and_accepts_cyrillic`.
- Two simultaneous first logins for the same username must not create duplicate profiles; pin with `test_concurrent_username_creation_returns_one_account`.
- Missing, invalid, or expired session cookies must not read or mutate another account's data; pin with `test_learning_api_requires_valid_account_session`, `test_expired_session_is_rejected`, and `test_session_cannot_access_another_account`.
- A regular staging profile must not gain admin access by changing browser requests; pin with `test_non_admin_cannot_call_admin_api`.
- Missing staging database or staging-gate credentials must fail closed instead of selecting the production `/data/questions.db` or exposing username-only profiles; pin with `test_web_settings_requires_explicit_database_path` and `test_staging_gate_rejects_missing_credentials`.

---

### Task 1: Isolated Web Runtime and Database Configuration

**Files:**
- Create: `webapp_settings.py`
- Create: `webapp_schema.py`
- Create: `web_main.py`
- Create: `tests/__init__.py`
- Modify: `webapp_server.py`
- Test: `tests/test_webapp_settings.py`
- Test: `tests/test_webapp_runtime.py`

**Interfaces:**
- `WebSettings.from_env() -> WebSettings` reads `AMEBA_WEB_DB_PATH`, `AMEBA_WEB_SESSION_SECRET`, `AMEBA_WEB_SESSION_TTL_SECONDS` (default `2592000`), `AMEBA_WEB_ADMIN_USERNAMES`, `AMEBA_WEB_BASE_URL`, and `AMEBA_WEB_HOST`/`AMEBA_WEB_PORT`; database path and session secret are required for standalone web startup. Staging additionally requires `AMEBA_STAGING_GATE_USER` and `AMEBA_STAGING_GATE_PASSWORD` for an outer HTTP Basic gate.
- `init_web_database(db_path: str) -> None` creates the standalone site's empty question, user, history, session, trial, access-grant, referral, and points schema idempotently; it never imports or calls `init_db.py`.
- Preserve `create_app(bot) -> web.Application` for the current Telegram Mini App; add `create_web_app(settings: WebSettings) -> web.Application` for standalone web use.
- `create_web_app()` stores its explicit database path in `app["db_path"]`; standalone startup fails if the path is omitted and all web database operations use this app-scoped path.
- `web_main.py` starts only `create_web_app()`; importing it must not create a Telegram `Bot`, start polling, or import `main.py`.

- [ ] **Step 1: Add settings tests** for required database path and session secret, valid host/port defaults, and malformed port values.
- [ ] **Step 2: Run settings tests** with `python -m unittest tests.test_webapp_settings -v`; confirm the missing-path test fails before implementation.
- [ ] **Step 3: Implement `WebSettings.from_env()`** with no fallback to `/data/questions.db`.
- [ ] **Step 4: Add runtime tests** proving that the standalone app uses the supplied temporary database, imports no bot polling entry point, and rejects requests missing valid staging HTTP Basic credentials.
- [ ] **Step 5: Implement the standalone core schema, `create_web_app()`, and `web_main.py`**; preserve `create_app(bot)` and existing `main.py` behavior for the production bot. Apply the Basic gate to the entire staging site, including static assets and APIs, and never log its credentials.
- [ ] **Step 6: Run the focused tests** and confirm the app opens only the configured temporary database and denies requests without the gate credentials.
- [ ] **Step 7: Commit** as `feat: add isolated web runtime`.

### Task 2: Username Profiles and Web Sessions

**Files:**
- Create: `webapp_accounts.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Test: `tests/test_webapp_accounts.py`
- Test: `tests/test_webapp_session_api.py`

**Interfaces:**
- `normalize_username(username: str) -> str` trims whitespace, applies Unicode NFC normalization and case folding, rejects empty values, control characters, and values longer than 32 characters.
- `Account` is an immutable record with `user_id: int`, `username: str`, and `is_admin: bool`; staging uses generated `users.user_id` values as internal account IDs for learning and referral tables.
- `create_or_get_account(db_path: str, username: str, admin_usernames: frozenset[str]) -> Account` atomically creates or finds one staging account and returns its internal integer ID and display username. Admin role is derived server-side from configuration, never from request data.
- `create_session(db_path: str, account_id: int, secret: bytes) -> str` returns a random session token while persisting only its hash.
- `resolve_session(db_path: str, token: str, secret: bytes) -> Account | None` resolves a valid session or returns `None`.
- `POST /api/session/login` accepts `{"username": "Руслан11"}`, creates or resumes an account, and sets an `HttpOnly`, `SameSite=Lax`, `Secure` cookie in HTTPS staging.
- `GET /api/session` returns the current account's display username and role; `POST /api/session/logout` revokes the session and clears the cookie.

- [ ] **Step 1: Add account tests** for trimmed and case-insensitive uniqueness, Cyrillic usernames, invalid input, and concurrent duplicate creation.
- [ ] **Step 2: Run account tests** with `python -m unittest tests.test_webapp_accounts -v`; confirm they fail on the clean schema.
- [ ] **Step 3: Create the staging `users` schema** in `init_web_database()` with generated internal IDs and a unique normalized username key; add a `web_sessions` table with hashed token and expiry.
- [ ] **Step 4: Implement account creation and session functions** with SQLite transactions and hashed random session tokens.
- [ ] **Step 5: Add session API tests** for login, session lookup, logout, invalid and expired cookies, and account isolation.
- [ ] **Step 6: Implement session handlers and a server-side `require_account(request)` helper**; return `401` for missing or invalid sessions.
- [ ] **Step 7: Run the focused test modules** and confirm no user-controlled request can assign an admin role.
- [ ] **Step 8: Commit** as `feat: add username staging sessions`.

### Task 3: Browser-Native Responsive Client

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/style.css`
- Test: `tests/test_web_client_contract.py`

**Interfaces:**
- The client uses same-origin `fetch()` with `credentials: "same-origin"` and session cookies; it sends no Telegram `Authorization` header.
- The client calls `GET /api/session` on startup and shows a username entry screen when there is no session.
- Browser back navigation uses the History API; Telegram BackButton and `Telegram.WebApp` are not referenced.

- [ ] **Step 1: Add client contract checks** asserting that the HTML does not load Telegram's script and the client does not reference `Telegram.WebApp`, `initData`, or Telegram authorization headers.
- [ ] **Step 2: Run the contract checks** with `python -m unittest tests.test_web_client_contract -v` and confirm they fail on the existing Mini App shell.
- [ ] **Step 3: Replace Telegram startup with username login and session restoration** in `static/app.js` using the Task 2 endpoints.
- [ ] **Step 4: Replace Telegram BackButton handling with browser navigation** while preserving direct navigation to learning routes.
- [ ] **Step 5: Update the viewport and responsive styles** so the same flows work at phone and desktop widths without disabling browser zoom.
- [ ] **Step 6: Run contract checks and inspect the app** at a narrow phone viewport and a desktop viewport; confirm login, refresh, and browser back behavior.
- [ ] **Step 7: Commit** as `feat: make the learning client browser-native`.

### Task 4: Learning APIs on Internal Account IDs

**Files:**
- Create: `learning_domain.py`
- Modify: `webapp_server.py`
- Modify: `main.py`
- Modify: `webapp_schema.py`
- Modify: `static/app.js`
- Test: `tests/test_learning_domain.py`
- Test: `tests/test_web_learning_api.py`

**Interfaces:**
- `choose_questions(questions: Sequence[tuple], limit: int, exclude_ids: Collection[int] = ()) -> list[tuple]` selects unique questions, excludes recent IDs when possible, and falls back to all questions when every ID is excluded.
- `is_answer_correct(selected: int, correct_option: int) -> bool` is the shared answer comparison used by both Telegram and web adapters.
- All learning endpoints resolve the caller through `require_account(request)` and pass `account.user_id` as the internal account ID to history, trials, and session storage.
- Keep existing endpoint shapes for `/api/config`, `/api/access`, `/api/exam/*`, `/api/test/*`, and `/api/review` where practical.
- Purchase endpoints are not registered by `create_web_app()`; the existing bot-mode app retains its current payment behavior. Staging access is granted by a web administrator.

- [ ] **Step 1: Add domain tests** for sampling, excluding recent IDs, fallback after all IDs were seen, and answer comparison.
- [ ] **Step 2: Run domain tests** with `python -m unittest tests.test_learning_domain -v` and confirm they fail before the module exists.
- [ ] **Step 3: Implement `learning_domain.py`** and route the existing bot and Mini App question selection and answer checks through these shared pure functions; preserve Telegram messages and session behavior.
- [ ] **Step 4: Add web API tests** for account-scoped history, exam start/answer/finish, practice next/answer, review, and unauthenticated requests using a temporary database.
- [ ] **Step 5: Run the API tests** with `python -m unittest tests.test_web_learning_api -v`; confirm the endpoints reject requests without username sessions.
- [ ] **Step 6: Implement web learning handlers** that resolve sessions through `require_account(request)` and use internal account IDs for session, history, trial, and access queries.
- [ ] **Step 7: Remove purchase navigation from the staging learning flow** and show current access state with a support/admin grant route instead.
- [ ] **Step 8: Run API tests** for two profiles and verify that one profile cannot read or alter another profile's exam, practice, or review state.
- [ ] **Step 9: Commit** as `feat: run learning flows with web accounts`.

### Task 5: Web Equivalents for Bot Operations and Admin

**Files:**
- Create: `webapp_operations.py`
- Create: `referral_domain.py`
- Modify: `webapp_schema.py`
- Modify: `webapp_server.py`
- Modify: `main.py`
- Modify: `static/admin.html`
- Modify: `static/admin.js`
- Modify: `static/admin.css`
- Modify: `static/app.js`
- Test: `tests/test_web_operations.py`
- Test: `tests/test_web_admin_api.py`
- Test: `tests/test_web_admin_client_contract.py`
- Test: `tests/test_referral_domain.py`

**Interfaces:**
- Support: `POST /api/support/tickets` creates a ticket; `GET /api/support/tickets` lists the current account's tickets; `GET /api/admin/support/tickets` lists tickets; `GET /api/admin/support/tickets/{ticket_id}` reads one; `POST /api/admin/support/tickets/{ticket_id}/replies` adds a reply visible to its owner.
- Announcements: `GET /api/announcements` lists notices; `POST /api/admin/announcements`, `PUT /api/admin/announcements/{id}`, and `DELETE /api/admin/announcements/{id}` manage them.
- Promo: `GET /api/promo` returns active promo content; `PUT /api/admin/promo` replaces it.
- Referrals: `GET /api/referral` returns a stable web invite URL based on `AMEBA_WEB_BASE_URL`, counts, and eligible non-purchase points for the current internal account. `POST /api/session/login` accepts an optional referral code captured from `?ref=...` and applies it once, rejecting self-referrals and duplicate attribution.
- `referral_level(referral_count: int) -> tuple[str, int, int]`, `record_points(conn, user_id, delta, reason, related_user_id=None, subject=None) -> None`, and `link_referrer(conn, user_id, referrer_id) -> bool` are shared domain operations used by the bot and web adapters with their own database connections.
- Admin access: `POST /api/admin/accounts/{user_id}/access` grants a subject; `DELETE /api/admin/accounts/{user_id}/access/{subject}` revokes it.
- Every admin route uses server-side role checks; browser-only visibility is not an authorization boundary.

- [ ] **Step 1: Add tests** for support ticket ownership and replies, announcement visibility, promo updates, referral URL and signup attribution, trial-based point awards, manual access changes, configured admin assignment, and rejection of non-admin API calls. In `tests/test_referral_domain.py`, cover referral thresholds, point ledger writes, self-referral rejection, and duplicate attribution.
- [ ] **Step 2: Add admin client contract checks** that `static/admin.html` loads no Telegram script and `static/admin.js` uses the web session instead of a static password token or Telegram `initData`.
- [ ] **Step 3: Run operations and client tests** with `python -m unittest tests.test_web_operations tests.test_web_admin_api tests.test_web_admin_client_contract tests.test_referral_domain -v` and confirm the new routes are absent or reject requests.
- [ ] **Step 4: Add staging tables** for support tickets, ticket replies, announcements, and promo content through `init_web_database()`.
- [ ] **Step 5: Implement `referral_domain.py`** and update the bot's referral wrappers plus `webapp_operations.py` to call the shared referral-level, attribution, and points-ledger functions; keep payment-specific awards disabled in web staging.
- [ ] **Step 6: Implement support, announcement, and promo services** in `webapp_operations.py`; replace direct bot message calls in standalone web routes with these services.
- [ ] **Step 7: Add administrator role enforcement and management routes** for announcements, promo, support, manual access, account lookup, and existing question/statistics screens. Admin usernames come only from `AMEBA_WEB_ADMIN_USERNAMES`; include the configured test administrator in fixtures.
- [ ] **Step 8: Replace the admin page's static password token and Telegram check** with the same session cookie and server-side role check used by the standalone site.
- [ ] **Step 9: Add web screens** for support tickets, announcements, referrals/points, and administrator operations; retain question editing and statistics.
- [ ] **Step 10: Run operations and admin tests** covering ownership, role escalation attempts, referral identity stability, and access grant/revoke.
- [ ] **Step 11: Commit** as `feat: add web support and admin workflows`.

### Task 6: Private Staging Deployment and Release Readiness

**Files:**
- Create: `Dockerfile.web`
- Create: `fly.staging.toml`
- Create: `.dockerignore`
- Create: `scripts/seed_web_staging.py`
- Modify: `web_main.py`
- Test: `tests/test_web_staging_seed.py`
- Test: `tests/test_web_release_smoke.py`

**Interfaces:**
- Staging uses a distinct Fly app and volume, an explicit `AMEBA_WEB_DB_PATH`, staging-only secrets, and an outer HTTP Basic gate; it never mounts or selects the production volume.
- `scripts/seed_web_staging.py` copies only question rows from a source SQLite database and creates synthetic fixtures; it does not copy user, purchase, points, session, referral, or history rows.
- The deployment starts `web_main.py` and does not start `main.py`, a Telegram bot, or `init_db.py`.

- [ ] **Step 1: Add seed tests** proving that only question catalog rows are copied and synthetic users are created.
- [ ] **Step 2: Implement and run the seed tests** against temporary source and destination databases.
- [ ] **Step 3: Add the web-only Docker and Fly staging configuration** with a distinct app name, distinct volume name, explicit DB path, and the staging-gate secrets; exclude local databases and secret files from the Docker build context.
- [ ] **Step 4: Add smoke tests** for username login, catalog, practice, exam, review, support, referral page, and admin question management.
- [ ] **Step 5: Run the full suite** with `python -m unittest discover -s tests -v`; expected result is all tests pass.
- [ ] **Step 6: Deploy only to the isolated staging app** after the user confirms the target Fly app and staging access restriction; verify health checks and confirm the production bot is unchanged.
- [ ] **Step 7: Complete phone and desktop acceptance** for user and administrator workflows. Before any public release, remove source-code credential fallbacks, rotate embedded credentials, and document authentication, payment, migration, and rollback work.
- [ ] **Step 8: Commit** as `chore: prepare private web staging`.
