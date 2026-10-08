# AMEBA Web Application Migration Design

Date: 2026-10-08

## Goal

Build AMEBA as one learning ecosystem: the website is the full learning and analytics experience, while the existing Telegram bot remains the daily companion for quick practice, reminders, and notifications. Users should be able to continue learning across both clients with the same account, progress, and existing subject access. The responsive website must work directly in desktop and mobile browsers.

The web application is not released to production until its agreed user and administrator workflows are complete and accepted. Payment processing remains a later phase. Website login uses Telegram identity so existing purchases remain associated with the same user.

## Current State

- `main.py` starts both the Telegram bot and the `aiohttp` web server in one process. The bot's user and access records are keyed by Telegram numeric user IDs.
- The browser client is plain HTML, CSS, and JavaScript under `static/`.
- `static/app.js` calls the Telegram Web App API and sends Telegram `initData` to the backend.
- `webapp_server.py` serves the current frontend and implements APIs for catalog, exams, practice, review, support, referrals, purchases, and administration.
- Learning sessions, history, access, and referral data currently use Telegram numeric user IDs.
- The admin panel already supports question management and statistics. Bot commands also handle promo text, access changes, support, announcements, and other operations.
- Production uses a persistent Fly volume for its database. Development must not connect to or write to that volume.

## Architecture

Keep the current Python `aiohttp` and static frontend stack for the first migration. Develop and validate the website through a web-only entry point that does not start Telegram polling. Do not change or deploy changes to the existing bot code, commands, or runtime as part of this phase. Keep the current bot-mode application behavior intact.

Use Telegram Login Widget to authenticate website users. The website backend validates Telegram's signed login response and its freshness; it never trusts a Telegram ID supplied as plain client input. The validated Telegram numeric ID is the canonical account key for this migration and maps directly to the existing `users.user_id`, purchases, history, trials, and sessions. This preserves current entitlements without issuing replacement purchases. Keep room for a future account-identity mapping layer so Google or other providers can later link to the same canonical account.

The widget requires associating the website domain with a Telegram bot in BotFather. This is a one-time domain configuration only; do not change the main bot's source code, commands, or deployment. Do not perform that external configuration as part of local implementation.

Keep Telegram-specific effects, such as sending bot messages, behind the existing bot adapter. The website uses browser-native pages, forms, notifications, and support tickets. The web client must not depend on Telegram Web App `initData` or a Telegram-specific authorization header; Telegram identity is established only through the server-validated login flow.

The web interface will be responsive for phone and desktop layouts. Existing learning flows can be evolved in place where they are useful, while the navigation and page structure should behave as a standalone website.

## Staging Identity

Website users authenticate with Telegram. The validated Telegram ID resolves to the existing account, so users keep the access and learning history already associated with that ID. Do not ask users to re-enter usernames or purchase receipts to restore access. Administrator privileges remain server-assigned and must not be derived from client data.

## Data Isolation and Migration

Run development and staging as a separate application with a separate database and storage volume. Seed only the question catalog and synthetic Telegram-ID fixtures, including synthetic purchases, access grants, referral relationships, and histories. Do not copy production personal user records or the production database into staging. The web application reads existing production account and purchase records only after a separately approved production integration; preserve Telegram IDs and entitlement rows so current purchasers retain access without duplicate grants.

The bot continues to use its existing production database and remains unchanged during web development. Since Telegram IDs remain canonical in this phase, initial web integration needs no account-ID remapping or purchase reissuance. Any future move to provider-neutral internal IDs must explicitly map Telegram IDs and preserve purchases/access, history, sessions, points, and referral relationships. Validate that migration before adopting it.

## Web Feature Scope

The first web migration establishes cross-client identity and delivers a useful web learning MVP. Payment processing stays out of scope; existing bot purchase/access records remain authoritative and are displayed and enforced by the website.

User workflows:

- Browse faculties, courses, and subjects.
- Practice questions and take timed exams.
- Review results, history, and incorrect answers.
- View referral links, referral counts, and eligible points. Purchase-based point awards remain inactive until payments are implemented.
- Create support tickets and read web announcements.
- Use existing access grants and purchase records for Telegram-authenticated accounts. Checkout and payment confirmation are not available in this phase.

Keep the learning domain extensible for later AI explanations, notes, flashcards, personalized plans, achievements, groups, progress comparisons, reminders, and subscription support. These are roadmap items, not MVP deliverables.

Administrator workflows:

- Search, filter, edit, and delete questions; view statistics.
- Manage promo content, announcements, support tickets, test users, and manual access grants.
- Review referral and points information needed to support the non-payment workflows.
- Payment receipt approval and other payment operations remain out of scope until the payment phase.

Telegram messages and bot-only commands get web equivalents for web users. Existing bot users continue to receive the current bot experience until a separately approved cutover.

## Delivery and Acceptance

Develop on the dedicated branch `codex/web-app-migration`, based on the clean repository revision. Keep unrelated working-tree changes on `main` untouched. Do not modify or deploy the main bot. Bot development can continue on its branch; reconcile later bot changes before the web branch is integrated. Use only synthetic user and purchase data in development and staging.

The web application is ready for a release decision only when:

- User and administrator workflows in scope have been exercised end to end on staging.
- The website works at phone and desktop viewport sizes.
- The website can start and perform its workflows without Telegram Web App client APIs or bot polling.
- Staging uses controlled Telegram-auth test fixtures, and its identity, roles, purchases, and data remain isolated from production.
- Existing purchasers retain website access by resolving the same verified Telegram ID against existing access records; no duplicate grants are created.
- Existing bot behavior and production data have not been changed by web staging.
- A production integration and rollback procedure is prepared and reviewed; no integration happens without a separate decision.

Production release requires a separate explicit decision after the agreed workflows are accepted. Payment integration remains a later phase. The current bot remains available until any future cutover is separately approved and complete.

## Security Requirements

- Keep staging restricted to testers and validate Telegram login signatures and freshness server-side.
- Store secrets in the deployment secret manager or environment, never as source-code fallbacks. Any credential previously committed or embedded in source must be rotated before public release.
- Enforce administrator roles on the server for every administrative API, not only in the browser UI.
- Validate and authorize access to user data by internal account ID.
