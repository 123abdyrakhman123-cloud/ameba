# AMEBA Web Application Migration Design

Date: 2026-10-07

## Goal

Make the web application the eventual primary product for AMEBA exam preparation. Users must be able to use it directly in a browser on both phones and computers, without depending on Telegram Web Apps or bot polling. The existing Telegram bot remains in production while the web application is developed and validated in isolation.

The web application is not released to production until its agreed user and administrator workflows are complete and accepted. Authentication and payment integrations are later phases; they are not prerequisites for private staging validation.

## Current State

- `main.py` starts both the Telegram bot and the `aiohttp` web server in one process.
- The browser client is plain HTML, CSS, and JavaScript under `static/`.
- `static/app.js` calls the Telegram Web App API and sends Telegram `initData` to the backend.
- `webapp_server.py` serves the current frontend and implements APIs for catalog, exams, practice, review, support, referrals, purchases, and administration.
- Learning sessions, history, access, and referral data currently use Telegram numeric user IDs.
- The admin panel already supports question management and statistics. Bot commands also handle promo text, access changes, support, announcements, and other operations.
- Production uses a persistent Fly volume for its database. Development must not connect to or write to that volume.

## Architecture

Keep the current Python `aiohttp` and static frontend stack for the first migration. Add a standalone web entry point that starts the web server without starting Telegram polling. Move learning and account-domain operations behind reusable service functions so the bot and web adapters can call the same rules where appropriate.

Keep Telegram-specific effects, such as sending bot messages, behind the bot adapter. The web interface uses browser-native pages, forms, notifications, and support tickets. The web client must not require `window.Telegram`, Telegram `initData`, or a Telegram-specific authorization header.

The web interface will be responsive for phone and desktop layouts. Existing learning flows can be evolved in place where they are useful, while the navigation and page structure should behave as a standalone website.

## Staging Identity

For private staging, a user enters a unique username such as `Руслан11`. The first entry creates a profile; later entry with the same username resumes that profile. The server assigns an immutable internal account ID. Username comparison is trimmed and case-insensitive so spelling or letter case cannot create duplicate accounts.

This username-only mode has no proof of account ownership. Staging must therefore be restricted to invited testers and must not be treated as production authentication. Administrator privileges are assigned only to explicit staging test accounts; users cannot grant themselves administrator access.

Future Google sign-in should link a verified Google identity to the internal account ID. A username must not be used as the database primary key or as proof of identity. Production release remains blocked until an appropriate authentication method is implemented.

## Data Isolation and Migration

Run staging as a separate application with a separate database and storage volume. Seed it with the question catalog and synthetic test accounts, access grants, referral relationships, and histories. Do not copy production personal user records into staging, and do not share the production SQLite database with staging.

The bot continues to use its existing production database and remains unchanged during web development. At a future cutover, take a fresh production snapshot and migrate records into the account-based model with explicit mappings from legacy Telegram user IDs. Preserve question history, exam sessions where appropriate, access grants, points, and referral relationships. Validate the migration before switching users to the web application.

## Web Feature Scope

The first web migration covers the bot's user and administrator workflows except payment processing and production authentication.

User workflows:

- Browse faculties, courses, and subjects.
- Practice questions and take timed exams.
- Review results, history, and incorrect answers.
- View referral links, referral counts, and eligible points. Purchase-based point awards remain inactive until payments are implemented.
- Create support tickets and read web announcements.
- Use staging access that administrators can grant or revoke manually. Checkout and payment confirmation are not available in this phase.

Administrator workflows:

- Search, filter, edit, and delete questions; view statistics.
- Manage promo content, announcements, support tickets, test users, and manual access grants.
- Review referral and points information needed to support the non-payment workflows.
- Payment receipt approval and other payment operations remain out of scope until the payment phase.

Telegram messages and bot-only commands get web equivalents for web users. Existing bot users continue to receive the current bot experience until a separately approved cutover.

## Delivery and Acceptance

Develop on the dedicated branch `codex/web-app-migration`, based on the clean repository revision. Keep unrelated working-tree changes on `main` untouched. Bot development can continue on its branch; reconcile later bot changes before the web branch is integrated.

The web application is ready for a release decision only when:

- User and administrator workflows in scope have been exercised end to end on staging.
- The website works at phone and desktop viewport sizes.
- The website can start and perform its workflows without Telegram client APIs or bot polling.
- Staging identity, roles, and data remain isolated from production.
- Existing bot behavior and production data have not been changed by web staging.
- A production data migration and rollback procedure is prepared and reviewed.

Production release requires a separate explicit decision after authentication and payment phases are complete. The current bot remains available until that decision and the data cutover are complete.

## Security Requirements

- Keep staging private because username-only profiles are claimable by anyone who can reach the site.
- Store secrets in the deployment secret manager or environment, never as source-code fallbacks. Any credential previously committed or embedded in source must be rotated before public release.
- Enforce administrator roles on the server for every administrative API, not only in the browser UI.
- Validate and authorize access to user data by internal account ID.
