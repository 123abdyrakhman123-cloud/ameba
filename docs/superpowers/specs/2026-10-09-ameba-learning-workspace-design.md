# Ameba Learning Workspace Design

## Goal

Turn the current minimal web client into a complete, responsive learning workspace inspired by the supplied Ameba dashboard reference. The web app should feel like a real study product on desktop and mobile, while the existing Telegram bot continues to run unchanged on its own branch and production resources.

## Product Scope

Implement the screens represented in the reference as connected, working web flows:

- Home dashboard with a prominent continue/start action, real catalog metrics, popular subjects, recommended tests, recent activity, and a compact progress/ranking view.
- Working navigation for Home, Tests, Subjects, Progress, Rating, Cards, and Profile.
- Subject catalog and test selection, using the existing faculty/course/subject catalog and each account's actual access.
- Timed exam flow with server-provided progress and timer, answer selection, and forward/back navigation that preserves previously selected answers.
- Exam result and answer review with score, accuracy, correct/error counts, elapsed time, and actionable review of missed questions.
- Progress page with completed web exam history, activity by subject, and streaks derived from saved activity dates.
- Rating page backed by real points data; use an opt-in pseudonym or a masked first name and never expose Telegram IDs, usernames, emails, or other account identifiers.
- Flashcards generated from real questions and correct answers, with per-account review state (new, known, repeat) and saved progress.
- Profile page showing the authenticated provider, display name, subject access, and logout.
- Responsive mobile dashboard and navigation, including a compact bottom navigation pattern and layouts that fit 375px-wide screens without horizontal scrolling.

The web app may display only values supported by stored data. It must not invent accuracy, streaks, rank, activity, or topic coverage. When an account has no saved activity, show an explicit empty state and a useful first action.

## Visual Direction

Use the supplied image as the visual reference, not as a pixel-perfect template. Preserve its recognizable structure:

- Desktop shell: fixed-width left navigation, a restrained top bar with search/account actions, a wide main column, and a narrow right rail for progress and ranking.
- Dashboard: an unframed hero area with the Ameba name, exam-preparation message, primary CTA, and a recognizable original mascot illustration; below it, compact metric tiles, subject shortcuts, and test cards.
- Exam: a focused question workspace with subject, question position, time, answer options, and clear previous/next controls.
- Results: score summary, actual completion metrics, missed-answer list, and review actions.
- Mobile: same information hierarchy in a single column, with a compact header and bottom navigation; no desktop sidebar or squeezed desktop grid.
- Shared style: clean white/light-neutral surfaces, restrained green as the primary action color, supporting teal/blue/red/amber states, readable Inter/system typography, visible focus states, and reduced-motion support. Use consistent small-radius controls; reserve stronger framing for individual question or repeated data items.
- Use an original Ameba-style mascot asset if the repository does not already contain an approved one. Do not copy bitmap content from the reference image.

## Data And Backend

Keep the existing Telegram and Google identity flows and their account isolation. The local demo account remains available only when explicitly enabled in local environment; it must never be enabled on staging or production.

Add web-owned persistence and authenticated API responses for capabilities not represented by the current data model:

- Completed exam summaries and answer-level results, scoped by provider/account key.
- Activity events/dates sufficient to calculate real progress and streaks.
- Flashcard state scoped by provider/account key and question.
- Dashboard aggregates, progress history, and leaderboard rows derived from persisted data.

Use existing question, subject, purchase, referral-points, and history data where available. Preserve Telegram account access by verified Telegram ID. Google-only records remain in web-owned tables. Existing Telegram question history can establish viewed/answered activity only where its semantics support that label; it cannot be used to infer correctness. Existing questions have no reliable topic taxonomy, so topic-level analytics must be omitted until explicit topic metadata exists. Persisted web exam answers may support subject-level analytics and question-level error review.

The existing exam rules remain authoritative unless the API already returns different values; the UI must render server-provided question counts and duration rather than hard-code the reference's sample values. Flashcard state and web analytics must not write to legacy bot tables. No production deployment, bot restart, BotFather change, or production database mutation is part of this work.

## Interaction Requirements

- The primary navigation entries are Home, Tests, Subjects, Progress, Rating, Cards, and Profile; each opens a working screen, not a placeholder.
- Every async screen has loading, empty, error, and success states.
- Search can find subjects and question text available to the authenticated account; results link into the relevant subject/test flow.
- Exam answers are validated against the active session; moving between questions preserves selected answers, and completion persists one result before showing analytics.
- Review navigation can move through every answered question and visibly distinguish selected, correct, and missed answers.
- Flashcards reveal the verified answer/explanation and allow saving a review state without exposing answers before reveal.
- Logout revokes the current web session and returns to login.
- Demo accounts remain visibly identified as demo and receive synthetic-only access/state.

## Acceptance Criteria

- Desktop dashboard at 1440px, tablet at 768px, and mobile at 375px render without overlap, clipped text, or horizontal scrolling.
- Dashboard metrics, recent activity, progress, rating, and result values are sourced from API/database records and have realistic zero-data states.
- A user can navigate from home to a subject, start a test/exam, answer questions, view results, review mistakes, return home, and use flashcards.
- Progress and flashcard state survive refresh and remain isolated between Telegram, Google, and demo accounts.
- The leaderboard does not reveal private account identifiers.
- Authentication, same-origin protection, admin separation, existing Telegram behavior, and database isolation remain covered by tests.
- Full test suite passes; browser interaction and screenshots are verified at desktop and mobile viewport sizes.
- The existing production bot source, bot static assets, deployment config, and production data are unchanged.

## Out Of Scope

- Changing the current Telegram bot or deploying this web app to production.
- Google/Telegram provider configuration, payment integration, or actual purchase processing.
- AI explanations, automatic topic classification, university groups, notifications, or personalized study-plan generation.
- Claiming historical answer accuracy where the source data does not record correctness.
