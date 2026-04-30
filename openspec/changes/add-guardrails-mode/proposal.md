# Change: Add `--guardrails-on` Discipline Mode

## Why

The existing `TradingGuard` (time gate + meeting gate) blocks impulsive *windows* but doesn't enforce *process discipline*. The trader still wants a mode that forces a deliberate session start, prevents pyramiding into a losing thesis, imposes a cooldown after meaningful losses, and adds friction to "keep going" past the daily goal. Checkboxes don't engage the brain — typed responses do.

## What Changes

- **New CLI flag** `--guardrails-on` for the click trader that enables a session-discipline lifecycle.
- **New module** `src/iborker/guardrails.py` containing the lifecycle state machine (clocked-out → countdown → checklist → arm prompt → armed → in-position → cooldown / goal-hit → re-arm).
- **Required env vars** when `--guardrails-on` is set; trader **fails noisily on startup** if any is missing:
  - `IB_DAILY_GOAL` (points)
  - `IB_LOSS_COOLDOWN_THRESHOLD` (points; e.g. `0.5`)
  - `IB_LOSS_COOLDOWN_SECONDS`
  - `IB_REARM_COOLDOWN_SECONDS`
  - `IB_CLOCK_IN_COUNTDOWN_MINUTES` (optional; defaults to `15`)
- **Clock-in flow**: all trade buttons start disabled; a "Clock In" button starts a countdown; on completion, a modal checklist appears with three free-text questions (≥20 chars each, tab-navigable); after submit, an "Arm iborker for trading?" yes/no modal; "yes" enables entry buttons.
- **No-pyramid + no-flip while in position**: entering a position disables BUY *and* SELL; only FLATTEN exits. Buttons re-enable after position closes (and any cooldown elapses).
- **Loss cooldown**: when a closed trade realizes a loss greater than `IB_LOSS_COOLDOWN_THRESHOLD`, all trade buttons disable for `IB_LOSS_COOLDOWN_SECONDS`. No re-checklist required — cooldown ends, buttons re-enable.
- **Goal-hit re-arm**: when cumulative session realized P&L hits `IB_DAILY_GOAL` after a close, trade buttons disable and a "Re-arm" button appears. Clicking it opens a modal requiring a typed reason (≥20 chars). After submit, a `IB_REARM_COOLDOWN_SECONDS` timer runs, then trade buttons re-enable.
- **Reverse forced off** when `--guardrails-on` is set, regardless of `--no-reverse`. (`--no-reverse` remains a standalone option for users who don't want the full discipline mode.)
- **Disconnect re-clocks-in**: if the IB session drops or the user disconnects mid-day, the lifecycle returns to clocked-out — no persisted state.
- **Session journal**: clock-in time, checklist answers, and re-arm reasons append to `workspace/journal/YYYY-MM-DD.md`.

## Impact

- **Affected specs**: New capability `guardrails-mode` (no existing spec to modify; the current `TradingGuard` time/meeting gates remain a separate concern that composes with this).
- **Affected code**:
  - `src/iborker/guardrails.py` — new module
  - `src/iborker/config.py` — new pydantic settings fields gated on guardrails mode
  - `src/iborker/trader.py` — wire up new mode, button-state machine, modal UI, journal hooks
  - `tests/test_guardrails.py` — new tests for state transitions and config validation
  - `.gitignore` — add `workspace/` so journals stay local
