# Custom Strategies Implementation Plan

> **For Codex:** Implement this plan task-by-task in the existing isolated source/release workflow.

**Goal:** Add configurable closed-candle strategies using built-in and restricted Python indicator outputs, persistent background monitoring, and explicitly armed trading through the existing gateway.

**Architecture:** The market service evaluates series and boolean conditions on completed candles, holding short subscription leases only for active monitors. The HTTPS trading service stores configurations/events in SQLite and runs a bounded scheduler. Auto execution uses the existing serialized TradeEngine preview/commit checks; process restart, logout and grant expiry disarm execution.

**Tech Stack:** Existing FastAPI, SQLite, isolated Python workers, React/TypeScript and Lightweight Charts.

1. Add pure configuration/rule validation and closed-candle evaluation; test crossing semantics, resets, incomplete bars, Python outputs and invalid input.
2. Add market evaluation endpoint and bounded subscription leases; retain shared subscriptions while monitors exist and expire idle leases.
3. Add strategy persistence, cursor/deduplication and bounded event log; baseline on start, skip missed candles, disarm on restart.
4. Add trade execution adapter using existing preview/commit, fresh quotes, price caps, pending-order/position checks and per-arm execution limits.
5. Expose authenticated strategy CRUD, test, start/stop and explicit arm/disarm APIs. Integrate low-frequency background scheduler without extending trading grants.
6. Build editor beneath charts with source selection/import from chart, configurable Python sources, buy/sell condition groups, order settings and visible event log. Default to signal-only monitoring.
7. Run backend tests, build, isolated Edge flows and read-only NAS checks. Deploy without touching OpenD or passwords; document limits and sync repository.

Initial scope: US stocks, 1/5/15/30/60-minute completed candles, one instrument/timeframe per strategy, all/any condition groups, built-in/Python series and constants. Multiple strategies can run independently. Signal-only monitors survive restart; automatic execution does not. No historical catch-up trades, no short selling, no unlimited execution or credentials persisted.
