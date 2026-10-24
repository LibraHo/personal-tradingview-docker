# Web trading terminal, first release

The user approved a web trading terminal first; Telegram/Agent integration is deferred.

## Scope

US stocks/ETFs only, whole shares, long positions and cash purchases. Account selection,
positions, balances, current orders, limit/market buys and sells, stop/stop-limit/trailing
sell orders, modification and cancellation. Quick presets support quantity, position
fractions and stop distances. Every mutation belongs to an explicit user action.
The first release offers a separate one-click stop action on filled positions; it does
not claim atomic bracket/OCO execution or manage an unattended entry/exit strategy.

## Architecture

The existing HTTP quote application remains read-only. A separate lightweight FastAPI
process serves /trade and /api/trade over TLS on 8443. Both use the same built frontend;
the trading process exposes no custom Python execution endpoints. It uses the installed
moomoo SDK, existing RSA connection and OpenD. A separate SQLite journal persists
order intents, outcomes and presets, never trading passwords or their MD5 equivalents.

The gateway has a one-time setup secret generated locally on NAS, a PBKDF2-derived
application password, Secure/HttpOnly/SameSite=Strict cookies, Origin and CSRF checks.
Real trade grants last at most 15 minutes, are bound to a browser session/account,
and are lost on restart. SDK unlock affects all OpenD connections; network access to
OpenD must remain restricted. A broker/API token incompatibility is surfaced unchanged
as a failed unlock; the service never disables a broker token.

## Execution invariants

- Explicit acc_id and environment, resolved against the broker account list.
- Preview is bound to browser/account/payload, expires after 20 seconds; commit checks again.
- Idempotent operation IDs persist before the broker call. Ambiguous outcomes are UNKNOWN;
  no automatic resubmission, reconciliation searches the broker's order remark.
- Serialized SDK access, finite HTTP waits, quota budget, no shorting or margin buys.
- Sell quantities checked against holdings and available quantity; pending sells block
  overselling. Modifications retain the existing side/type/session, and have their own preview.
- STOP and trailing orders only RTH in this release; paper only NORMAL/MARKET DAY/RTH.
- A submitted order is not labeled filled/protected until broker state says so.
- No credentials in URLs, logs, localStorage or journal. HTTPS is required for authentication.

## Validation

Inject a fake broker only in tests to exercise duplicate requests, unknown outcomes,
account/environment mismatch, expired grants, overselling, invalid precision, unsupported
session/order combinations and mutation revalidation. Browser tests use isolated test
accounts and an injected test adapter; production account/position calls are read-only.
Never place live or paper orders on the user's account as part of automated verification.

Official docs: https://openapi.moomoo.com/moomoo-api-doc/en/trade/overview.html
https://openapi.moomoo.com/moomoo-api-doc/en/trade/unlock.html
https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html
