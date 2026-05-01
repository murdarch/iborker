## MODIFIED Requirements

### Requirement: Required Configuration Validation

When `--guardrails-on` is set, the trader SHALL validate that required environment variables are present *before* the GUI launches and SHALL exit with a non-zero status and a clear error if any are missing.

Required env vars:
- `IB_DAILY_GOAL` (float, points)
- `IB_LOSS_COOLDOWN_THRESHOLD` (float, points)
- `IB_LOSS_COOLDOWN_SECONDS` (int)
- `IB_REARM_COOLDOWN_SECONDS` (int)
- `IB_TRADE_COOLDOWN_SECONDS` (int)
- `IB_MAX_ROUND_TRIPS` (int)

Optional env var with default:
- `IB_CLOCK_IN_COUNTDOWN_MINUTES` (int, default `15`)

#### Scenario: Missing required vars
- **WHEN** `--guardrails-on` is set and `IB_DAILY_GOAL` is unset
- **THEN** the process exits with non-zero status before the GUI is created
- **AND** stderr lists every missing required env var by name

#### Scenario: All required vars present
- **WHEN** `--guardrails-on` is set and all required env vars are present
- **THEN** the trader launches normally and enters `CLOCKED_OUT`

## ADDED Requirements

### Requirement: Guardrails Mode Activation

The click trader SHALL accept a `--guardrails-on` CLI flag that activates a session-discipline lifecycle. When the flag is absent, behavior MUST be unchanged from the default click trader.

#### Scenario: Flag absent
- **WHEN** the trader is launched without `--guardrails-on`
- **THEN** all trade buttons are usable per existing time-gate / meeting-gate rules
- **AND** no clock-in, checklist, cooldown, or re-arm UI is shown

#### Scenario: Flag present
- **WHEN** the trader is launched with `--guardrails-on`
- **THEN** the lifecycle starts in `CLOCKED_OUT`
- **AND** all trade buttons (BUY, SELL, FLATTEN) are disabled
- **AND** a "Clock In" button is visible
- **AND** the REVERSE button is not rendered, regardless of `--no-reverse`

### Requirement: Clock-In Countdown

When the user clicks "Clock In" from `CLOCKED_OUT`, the lifecycle SHALL enter `COUNTDOWN` for `IB_CLOCK_IN_COUNTDOWN_MINUTES` minutes. The countdown SHALL be visible in the UI. Trade buttons MUST remain disabled throughout.

#### Scenario: Countdown elapses
- **WHEN** the countdown reaches zero
- **THEN** the lifecycle transitions to `CHECKLIST`

#### Scenario: User cancels during countdown
- **WHEN** the user clicks a "Cancel" affordance during `COUNTDOWN`
- **THEN** the lifecycle returns to `CLOCKED_OUT`

### Requirement: Pre-Trade Checklist

In `CHECKLIST`, the trader SHALL present a modal with three free-text questions and SHALL NOT advance until the user submits responses each at least 20 characters long. Fields MUST be tab-navigable.

The three questions are:
1. "Are channel, traverse and tape trendlines drawn?"
2. "What economic events are on the calendar?"
3. "Was first bar volume abnormal (<30k)?"

#### Scenario: User submits valid responses
- **WHEN** all three responses are ≥20 characters and the user clicks Submit
- **THEN** responses are appended to the daily journal at `workspace/journal/YYYY-MM-DD.md`
- **AND** the lifecycle transitions to `ARM_PROMPT`

#### Scenario: User submits a response under 20 chars
- **WHEN** any response is under 20 characters and the user clicks Submit
- **THEN** the offending field is highlighted and the modal does not close
- **AND** the lifecycle remains in `CHECKLIST`

#### Scenario: User cancels checklist
- **WHEN** the user cancels the checklist modal
- **THEN** the lifecycle returns to `CLOCKED_OUT`

### Requirement: Arm Prompt

After checklist submit, the trader SHALL present an "Arm iborker for trading?" yes/no modal. Only "yes" enables trade buttons.

#### Scenario: User confirms
- **WHEN** user clicks "yes" in the arm prompt
- **THEN** the lifecycle transitions to `ARMED`
- **AND** BUY, SELL, and FLATTEN are enabled (subject to existing time/meeting guard)

#### Scenario: User declines
- **WHEN** user clicks "no" in the arm prompt
- **THEN** the lifecycle returns to `CLOCKED_OUT`

### Requirement: No Pyramid or Flip While In Position

When the user holds a non-zero position in `--guardrails-on` mode, BUY and SELL SHALL both be disabled. Only FLATTEN MAY be used to exit. Buttons SHALL re-enable upon return to `ARMED` after a close.

#### Scenario: User enters a long
- **WHEN** position transitions from 0 to +N
- **THEN** the lifecycle transitions to `IN_POSITION`
- **AND** BUY is disabled
- **AND** SELL is disabled
- **AND** FLATTEN is enabled

#### Scenario: User enters a short
- **WHEN** position transitions from 0 to −N
- **THEN** the lifecycle transitions to `IN_POSITION`
- **AND** BUY is disabled
- **AND** SELL is disabled
- **AND** FLATTEN is enabled

### Requirement: Loss Cooldown

When a close transitions position from non-zero to zero and the realized P&L for that close is a loss greater than `IB_LOSS_COOLDOWN_THRESHOLD` points, the trader SHALL disable all trade buttons for `IB_LOSS_COOLDOWN_SECONDS` seconds. No re-checklist is required after the cooldown expires.

#### Scenario: Loss exceeds threshold
- **GIVEN** `IB_LOSS_COOLDOWN_THRESHOLD = 0.5` and `IB_LOSS_COOLDOWN_SECONDS = 120`
- **WHEN** a close realizes −0.75 pts on the closed portion
- **THEN** the lifecycle transitions to `LOSS_COOLDOWN`
- **AND** BUY, SELL, and FLATTEN are disabled
- **AND** after 120 seconds the lifecycle transitions to `ARMED`

#### Scenario: Loss within threshold
- **GIVEN** `IB_LOSS_COOLDOWN_THRESHOLD = 0.5`
- **WHEN** a close realizes −0.25 pts
- **THEN** no cooldown is triggered
- **AND** the lifecycle transitions back to `ARMED`

### Requirement: Daily Goal Re-Arm

When a close pushes cumulative session realized points to or past `IB_DAILY_GOAL`, the trader SHALL disable trade buttons and present a "Re-arm" button. Clicking it SHALL open a modal requiring a typed reason of at least 20 characters. After submission, a `IB_REARM_COOLDOWN_SECONDS` timer SHALL run before trade buttons re-enable.

#### Scenario: Cumulative crosses goal
- **GIVEN** `IB_DAILY_GOAL = 4.0` and current cumulative = 3.5
- **WHEN** a close adds +0.75 pts (new cumulative 4.25)
- **THEN** the lifecycle transitions to `GOAL_HIT`
- **AND** trade buttons are disabled
- **AND** a "Re-arm" button is visible

#### Scenario: User submits re-arm reason
- **WHEN** the user types a reason ≥20 chars and submits
- **THEN** the reason is appended to the daily journal
- **AND** the lifecycle transitions to `REARM_COOLDOWN`
- **AND** after `IB_REARM_COOLDOWN_SECONDS` the lifecycle transitions to `ARMED`

#### Scenario: Re-arm reason too short
- **WHEN** the user submits a reason under 20 chars
- **THEN** the modal does not close and the field is highlighted

### Requirement: Disconnect Re-Clocks-In

If the IB connection is dropped or the user explicitly disconnects while `--guardrails-on` is active, the lifecycle SHALL return to `CLOCKED_OUT`. State is not persisted across disconnects.

#### Scenario: User clicks Disconnect mid-session
- **WHEN** the trader is in any state and the user disconnects
- **THEN** the lifecycle resets to `CLOCKED_OUT`
- **AND** trade buttons are disabled

### Requirement: Session Journal

When `--guardrails-on` is active, the trader SHALL append events to `workspace/journal/YYYY-MM-DD.md` (local date). Events MUST include clock-in time, full checklist responses, and re-arm reasons with their timestamps.

#### Scenario: Checklist submitted
- **WHEN** the user submits the pre-trade checklist
- **THEN** the journal file for today contains a timestamped entry with all three responses verbatim

#### Scenario: Re-arm reason submitted
- **WHEN** the user submits a re-arm reason
- **THEN** the journal file for today contains a timestamped entry with the reason verbatim

### Requirement: Per-Trade Cooldown

When a close transitions position from non-zero to zero and does not trigger LOSS_COOLDOWN, GOAL_HIT, or MAX_TRADES_HIT, the trader SHALL disable all trade buttons for `IB_TRADE_COOLDOWN_SECONDS` seconds before returning to `ARMED`. The per-trade cooldown is mutually exclusive with the loss cooldown — a single close triggers exactly one of them.

#### Scenario: Win triggers per-trade cooldown
- **GIVEN** `IB_TRADE_COOLDOWN_SECONDS = 30`
- **WHEN** a close realizes +0.5 pts (no other lockout fires)
- **THEN** the lifecycle transitions to `TRADE_COOLDOWN`
- **AND** trade buttons are disabled
- **AND** after 30 seconds the lifecycle transitions to `ARMED`

#### Scenario: Small loss triggers per-trade cooldown
- **GIVEN** `IB_LOSS_COOLDOWN_THRESHOLD = 0.5` and `IB_TRADE_COOLDOWN_SECONDS = 30`
- **WHEN** a close realizes −0.25 pts
- **THEN** the lifecycle transitions to `TRADE_COOLDOWN` (not `LOSS_COOLDOWN`)
- **AND** trade buttons are disabled until the trade cooldown elapses

#### Scenario: Big loss takes precedence
- **GIVEN** `IB_LOSS_COOLDOWN_THRESHOLD = 0.5`
- **WHEN** a close realizes −1.0 pts
- **THEN** the lifecycle transitions to `LOSS_COOLDOWN` (not `TRADE_COOLDOWN`)

### Requirement: Max Round Trips Terminal Lockout

The trader SHALL count round trips (entry-to-flat cycles) per session. When the count reaches `IB_MAX_ROUND_TRIPS`, the lifecycle SHALL enter `MAX_TRADES_HIT` and remain there until clock-out (disconnect / next session). The lockout is terminal — no re-arm path, no typed-reason override.

The round-trip counter SHALL reset on `clock_out()` and on `clock_in()`.

#### Scenario: Max trips reached
- **GIVEN** `IB_MAX_ROUND_TRIPS = 3` and 2 round trips already taken
- **WHEN** the third round trip closes
- **THEN** the lifecycle transitions to `MAX_TRADES_HIT`
- **AND** trade buttons are disabled
- **AND** no Re-arm button is shown

#### Scenario: Max trips precedence over other cooldowns
- **GIVEN** the close that completes the max trip would otherwise be a big loss
- **WHEN** round trips reach `IB_MAX_ROUND_TRIPS`
- **THEN** the lifecycle is `MAX_TRADES_HIT` (not `LOSS_COOLDOWN`)

#### Scenario: Counter resets on clock-out
- **GIVEN** the lifecycle is `MAX_TRADES_HIT` after 3 round trips
- **WHEN** the user disconnects (or `clock_out()` is invoked)
- **THEN** the lifecycle returns to `CLOCKED_OUT`
- **AND** the round-trip counter is `0`
