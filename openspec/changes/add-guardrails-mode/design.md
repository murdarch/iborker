## Context

The click trader is a personal tool for the project author. The guardrails-on mode is shaped by the author's actual trading psychology challenges — opening-bell impulsiveness, pyramiding into losing trades, and chasing past the day's goal. The mode is opt-in (default off) so third-party users and casual sessions are unaffected.

The existing `TradingGuard` in `src/iborker/trading_guard.py` (time gate + calendar meeting gate) is unchanged and composes with this new mode: when `--guardrails-on` is set, both must pass for buttons to be enabled.

## Goals / Non-Goals

**Goals**
- Force a deliberate, typed-response session start.
- Make pyramiding and flipping mechanically impossible while in a position.
- Cool the trader off after meaningful losses.
- Add typed-reason friction to trading past the daily goal.
- Keep state in-memory; no persistence, no DB.

**Non-Goals**
- Position sizing / Kelly logic.
- Auto-flatten on goal hit (the user wants to stay in the trade until *they* exit).
- Mobile or remote arming.
- Replacing the existing time/meeting `TradingGuard`.

## Decisions

### Decision: Single `GuardrailsState` enum drives all UI

```
CLOCKED_OUT  → only "Clock In" visible; trade buttons disabled
COUNTDOWN    → countdown timer visible; trade buttons disabled
CHECKLIST    → modal blocks UI; trade buttons disabled
ARM_PROMPT   → modal blocks UI; trade buttons disabled
ARMED        → entry buttons enabled when position == 0
IN_POSITION  → BUY+SELL disabled, FLATTEN enabled
LOSS_COOLDOWN → all trade buttons disabled until timer expires → ARMED
GOAL_HIT     → trade buttons disabled, "Re-arm" button visible
REARM_PROMPT → modal blocks UI for typed reason
REARM_COOLDOWN → all trade buttons disabled until timer expires → ARMED
```

Single enum → one `_apply_guardrails_state()` method → predictable UI. Alternatives considered: nested booleans (rejected — combinatorial explosion); separate state per concern (rejected — coordination bugs).

### Decision: Both BUY and SELL disabled while in position

The user's stated rule was "if long, buy is disabled" to prevent pyramiding. But sell-while-long can flatten *or* flip depending on quantity, and flipping is the same risk-shape as Reverse, which is forbidden in this mode. Strictest reading: in position, only FLATTEN works for exit. This eliminates a category of footguns and is consistent with the no-reverse rule.

### Decision: Modals via DearPyGui's `dpg.window(modal=True, popup=True)`

Native to the existing GUI framework, no new dependency. Tab-navigable text inputs come for free with `dpg.add_input_text(multiline=True)` and DearPyGui's focus order. Alternatives considered: separate Tkinter window (rejected — extra dependency, focus issues); inline panel (rejected — too easy to ignore).

### Decision: Required env vars validated at startup before GUI launch

`Settings.guardrails_required()` is called from `cli()` immediately after parsing `--guardrails-on`. Missing vars raise `ConfigError` with the list of missing names. This means the trader fails before `dpg.create_context()`, so the user sees the error in the terminal where they ran the command, not in a half-built GUI.

### Decision: Loss cooldown triggers on *realized* loss only

We use the existing `_calculate_realized_pnl` machinery in `trader.py:369`. The trigger is "after a close, the realized portion was a loss greater than threshold". Unrealized drawdown does not trigger cooldown — that would punish patience. A close that takes the position from non-zero to zero is what we evaluate.

### Decision: Goal-hit check uses `daily_realized_points`, not dollars

The trader already tracks `daily_realized_points` (per-contract, points, mode-independent). `IB_DAILY_GOAL` is points. This is consistent regardless of the user's $/pts toggle.

### Decision: Reverse is hidden, not just disabled, in guardrails mode

When `--guardrails-on` is set, `self.no_reverse = True` is forced regardless of the CLI flag. The button is never created. Cleaner than disabling — there's no surface to even consider.

## Risks / Trade-offs

- **Risk**: User wants to abort the checklist mid-fill (e.g. realizes they don't actually want to trade today). **Mitigation**: cancel button on each modal returns to `CLOCKED_OUT`. No partial-credit; full re-do next time.
- **Risk**: Disconnect-induced re-clock-in is annoying if the network blips. **Mitigation**: explicit user choice — they said "don't let me flail". Document that the time-gate already establishes a "cost" to re-clocking-in.
- **Risk**: Journal file grows during long sessions or if the user clears and re-clocks-in many times. **Mitigation**: append-only, dated daily; trivial to rotate or grep.
- **Trade-off**: No persistence of session state means a crash mid-trade puts the user back at clocked-out even if positions remain open at the broker. This is acceptable — flatten remains usable through standard IB tools, and the trader will re-discover the position on reconnect, at which point IN_POSITION is the right state to enter (with entry buttons disabled).

## Migration Plan

Net-new feature; no migration. Default behavior is unchanged when `--guardrails-on` is not passed. The existing `--no-reverse` flag continues to work standalone.

## Open Questions

- Should the journal also log trade close events (entry, exit, P&L)? Out of scope for this change; could be a follow-up.
- Should clocking out be an explicit action (a "Clock Out" button in `ARMED`)? Probably yes for completeness; included as a small task.
