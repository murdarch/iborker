# Implementation Tasks

## 1. Configuration

- [x] 1.1 Add `daily_goal: float | None`, `loss_cooldown_threshold: float | None`, `loss_cooldown_seconds: int | None`, `rearm_cooldown_seconds: int | None`, `clock_in_countdown_minutes: int = 15` to `IBSettings` in `src/iborker/config.py`
- [x] 1.2 Add `IBSettings.guardrails_required()` classmethod returning `list[str]` of missing required env vars
- [x] 1.3 Add `.gitignore` entry for `workspace/`

## 2. Guardrails state machine

- [x] 2.1 Create `src/iborker/guardrails.py` with `GuardrailsState` enum (`CLOCKED_OUT`, `COUNTDOWN`, `CHECKLIST`, `ARM_PROMPT`, `ARMED`, `IN_POSITION`, `LOSS_COOLDOWN`, `GOAL_HIT`, `REARM_PROMPT`, `REARM_COOLDOWN`)
- [x] 2.2 Implement `GuardrailsLifecycle` class holding state, timer deadlines, checklist responses, re-arm reasons, and a `tick(position: int, daily_realized: float)` method that handles auto-transitions (countdown→checklist, cooldown→armed, etc.)
- [x] 2.3 Implement `clock_in()`, `submit_checklist(answers)`, `arm()`, `cancel()`, `register_close(realized_pts: float)`, `request_rearm(reason: str)`, `clock_out()` actions
- [x] 2.4 Define `CHECKLIST_QUESTIONS` constant with the three trendline / calendar / first-bar-volume prompts and `MIN_RESPONSE_CHARS = 20`

## 3. Journal

- [x] 3.1 Add `src/iborker/journal.py` with `append(entry: str)` writing to `workspace/journal/YYYY-MM-DD.md`
- [x] 3.2 Hook journal calls into `clock_in`, `submit_checklist`, `request_rearm`

## 4. CLI + startup validation

- [x] 4.1 Add `--guardrails-on` flag to `cli()` in `src/iborker/trader.py`
- [x] 4.2 In `cli()`, after parsing, if `--guardrails-on` is set, call `IBSettings.guardrails_required()` and exit with a clear error listing missing env vars before `main()` runs
- [x] 4.3 When `--guardrails-on` is set, force `no_reverse = True`

## 5. Trader UI integration

- [x] 5.1 Add `self._lifecycle: GuardrailsLifecycle | None` to `ClickTrader.__init__`; `None` when `--guardrails-on` is off
- [x] 5.2 Add `_apply_guardrails_state()` that maps `GuardrailsState` → button enabled/disabled and theme
- [x] 5.3 Render "Clock In" button + countdown text, hidden when `--guardrails-on` is off
- [x] 5.4 Build checklist modal: three `dpg.add_input_text(multiline=True)` fields, tab-navigable, submit button validates ≥20 chars per answer
- [x] 5.5 Build "Arm iborker for trading?" yes/no modal
- [x] 5.6 Build "Re-arm" button (visible only in `GOAL_HIT`) and re-arm reason modal
- [x] 5.7 In `_update_display()`, call `lifecycle.tick(position, daily_realized_points)` then `_apply_guardrails_state()`
- [x] 5.8 In `place_order` after a close, call `lifecycle.register_close(realized_points)` so loss cooldown / goal-hit transitions fire
- [x] 5.9 In `disconnect()`, transition lifecycle back to `CLOCKED_OUT`
- [x] 5.10 Disable BUY and SELL when `state == IN_POSITION`; keep FLATTEN enabled

## 6. Tests

- [x] 6.1 `tests/test_guardrails.py`: state transitions for happy path (clock-in → countdown → checklist → arm → armed)
- [x] 6.2 Loss cooldown triggers on close with realized loss > threshold; does not trigger on smaller losses
- [x] 6.3 Goal-hit transitions on close that pushes cumulative ≥ daily goal
- [x] 6.4 Re-arm requires typed reason ≥ 20 chars; cooldown elapses → armed
- [x] 6.5 Checklist rejects answers under 20 chars
- [x] 6.6 `IBSettings.guardrails_required()` returns the right missing-var list
- [x] 6.7 `register_close` in `IN_POSITION` returns to `ARMED` cleanly when no cooldown / goal trigger

## 7. Docs

- [x] 7.1 README section: `--guardrails-on` flag, required env vars, lifecycle summary
- [x] 7.2 Mention in `--help` text

## 8. Refinements (post-day-1 use)

- [x] 8.1 Add `trade_cooldown_seconds: int | None` and `max_round_trips: int | None` to `IBSettings`; extend `guardrails_required()` to require them
- [x] 8.2 Add `TRADE_COOLDOWN` and `MAX_TRADES_HIT` to `GuardrailsState`; add `trade_cooldown_seconds: int` and `max_round_trips: int` to `GuardrailsConfig`
- [x] 8.3 Add `round_trips: int = 0` to `GuardrailsLifecycle`; reset to 0 in `clock_in()` and `clock_out()`
- [x] 8.4 In `register_close()`, increment `round_trips` first, then evaluate priority chain: `MAX_TRADES_HIT` > `LOSS_COOLDOWN` > `GOAL_HIT` > `TRADE_COOLDOWN`
- [x] 8.5 In `tick()`, expire `TRADE_COOLDOWN` to `ARMED`
- [x] 8.6 Update `entry_buttons_enabled` / `flatten_enabled` so `MAX_TRADES_HIT` and `TRADE_COOLDOWN` disable everything
- [x] 8.7 Pass new config fields from `trader.main()` into `GuardrailsConfig`
- [x] 8.8 Show round-trip counter in lifecycle status text
- [x] 8.9 Tests: trade cooldown after win, after small loss; max trips terminal; precedence over loss cooldown; counter reset on clock_out
- [x] 8.10 Update README env-vars table and lifecycle summary
