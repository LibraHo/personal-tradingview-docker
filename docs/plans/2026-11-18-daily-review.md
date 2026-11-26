# Daily Review Implementation Plan

**Goal:** Add a peer workspace for separate CN and US trading journals, editable discipline checklists, related symbols, and weekly improvement reviews.

**Architecture:** React workspace using the shared market selector and theme. Store journals and rules in the existing NAS SQLite database through a dedicated FastAPI module; expose the same endpoints through the authenticated chart gateway. Daily rule snapshots preserve historical labels; optimistic revisions prevent accidental overwrites. Keep local drafts until the server confirms a save.

**Tech Stack:** React 19, TypeScript, FastAPI, SQLite, unittest, Vite.

### 1. Durable journal and API
- Add `tests/test_review.py`: market isolation, upsert/revision conflicts, discipline lifecycle/snapshots, symbol validation, week boundaries/statistics, weekly focus, persistence, export.
- Run new tests and confirm missing-feature failure.
- Add `app/review.py`, register in `app/main.py`, allow narrowly scoped review routes in `app/chart_gateway.py`.
- Run new tests and gateway authentication regressions.

### 2. Daily review workspace
- Add `web/src/DailyReview.tsx`, `web/src/daily-review.css` and small typed API/draft helpers.
- Daily editor: market/date, traded/no-trade, violated disciplines, reasons, lessons, next-day plan, related stocks with individual notes.
- Discipline manager: add, rename, pause/reactivate. Keep historical snapshot labels.
- Weekly panel: reviewed days, clean days, ranked violations with previous-week comparison, editable focus/action/summary.
- History: calendar-month entries, jump to prior days. Export all saved records as JSON.
- Preserve unsaved daily/weekly drafts across navigation and failures, show errors, and reject stale updates.
- Add lazy workspace entry next to radar, including mobile selector, chart visibility and direct `?view=review` access.

### 3. Verification
- Run journal API tests and existing related service tests; run TypeScript/Vite build.
- Exercise the page in a real browser: create rules, record violations and stocks, save/reload, switch markets/dates, weekly summaries, narrow viewport, both themes.
- Prepare built frontend in the app's static output. Record the exact delivery status and any remaining deployment limitation.

Design decisions: CN dates use Shanghai time; US dates use New York time with manual date selection. Weeks run Monday–Sunday. Unrecorded dates are excluded from compliance statistics. A checked discipline always means a violation, and one discipline counts at most once per recorded day.
