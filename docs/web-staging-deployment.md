# Web Staging Deployment

This is a preparation checklist, not authorization to create or deploy a remote app. The staging Fly app name, domain, and region must be reviewed and approved before any remote action. Never use the bot app `ameba-bot`, its `ameba_data` volume, or `/data/questions.db`.

## Isolated Resources

- Choose and approve a unique staging app name, public hostname, and region. Replace `ameba-web-staging-unconfigured` and the matching `.fly.dev` URL in `fly.staging.toml` only after that decision.
- Provision a separate Fly volume named `ameba_web_staging_data`, mounted only at `/data-web` for the web app.
- Configure these secrets on the staging app only: `AMEBA_WEB_SESSION_SECRET`, `AMEBA_TELEGRAM_LOGIN_BOT_TOKEN`, `AMEBA_TELEGRAM_LOGIN_BOT_USERNAME`, `AMEBA_GOOGLE_CLIENT_ID`, `AMEBA_STAGING_GATE_USER`, and `AMEBA_STAGING_GATE_PASSWORD`.
- Set `AMEBA_WEB_ADMIN_IDS` to the reviewed Telegram administrator IDs. It must not be copied from production configuration without review.
- Configure the Google authorized origin and Telegram Login Widget domain only after the staging hostname is approved. BotFather changes remain a separate, user-controlled step.

## Database Seed

Prepare an offline sanitized SQLite file containing the question catalog, then seed a new destination path on the staging volume. The seeder reads only `questions`; it does not copy source users, purchases, sessions, history, referrals, or points. It creates one synthetic Telegram account and one synthetic Google account with web-only progress. It rejects `/data/questions.db` as either source or destination and refuses to replace a non-empty destination.

The fixture Telegram ID is `900000001`; the Google subject is `staging-google-subject`. These are test fixtures, not real users. Never use real account rows as seed data.

## Release Gate

Before a deployment is approved, verify the resolved app name and volume are separate from the production bot, all required secrets are set on staging only, the Basic gate is enabled, `/healthz` returns `200`, and both provider flows plus the release smoke suite pass. Do not run `fly deploy`, create the app/volume, or change BotFather settings as part of this preparation task.
