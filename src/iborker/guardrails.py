"""Guardrails-mode lifecycle: clock-in, checklist, cooldowns, goal-hit re-arm.

Used by the click trader when launched with `--guardrails-on`.  Composes with
the existing `TradingGuard` (time/meeting gates) — both must pass for trade
buttons to be enabled.

The lifecycle is driven by:
- explicit user actions: `clock_in`, `submit_checklist`, `arm`, `cancel`,
  `request_rearm`, `clock_out`
- explicit trader notifications: `register_entry`, `register_close`
- passive `tick()` calls from the UI render loop, which advance any
  time-based transitions (countdown, cooldowns)

The state machine is intentionally small and string-keyed so logging /
journaling stays readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum


class GuardrailsState(str, Enum):
    CLOCKED_OUT = "clocked_out"
    COUNTDOWN = "countdown"
    CHECKLIST = "checklist"
    ARM_PROMPT = "arm_prompt"
    ARMED = "armed"
    IN_POSITION = "in_position"
    TRADE_COOLDOWN = "trade_cooldown"
    LOSS_COOLDOWN = "loss_cooldown"
    GOAL_HIT = "goal_hit"
    REARM_PROMPT = "rearm_prompt"
    REARM_COOLDOWN = "rearm_cooldown"
    MAX_TRADES_HIT = "max_trades_hit"


CHECKLIST_QUESTIONS: tuple[str, ...] = (
    "Are channel, traverse and tape trendlines drawn?",
    "What economic events are on the calendar?",
    "Was first bar volume abnormal (<30k)?",
)

MIN_RESPONSE_CHARS = 20


@dataclass
class GuardrailsConfig:
    """Validated config for guardrails mode (all required at construction)."""

    daily_goal: float
    loss_cooldown_threshold: float
    loss_cooldown_seconds: int
    rearm_cooldown_seconds: int
    trade_cooldown_seconds: int
    max_round_trips: int
    clock_in_countdown_minutes: int = 15


@dataclass
class GuardrailsLifecycle:
    """Session lifecycle for guardrails mode.

    Holds state, timer deadlines, and the most recent checklist responses /
    re-arm reason.  All time math is in UTC and timer-based transitions
    are surfaced by `tick()`.
    """

    config: GuardrailsConfig
    state: GuardrailsState = GuardrailsState.CLOCKED_OUT
    deadline: datetime | None = None
    last_checklist: tuple[str, ...] = field(default_factory=tuple)
    last_rearm_reason: str = ""
    round_trips: int = 0

    # ── Internal helpers ───────────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _set_deadline(self, seconds: float) -> None:
        self.deadline = self._now() + timedelta(seconds=seconds)

    def remaining_seconds(self) -> float:
        """Seconds left on the active deadline, or 0 if none / past."""
        if self.deadline is None:
            return 0.0
        delta = (self.deadline - self._now()).total_seconds()
        return max(0.0, delta)

    # ── Passive tick ───────────────────────────────────────────────────────

    def tick(self) -> None:
        """Advance time-based transitions.

        Idempotent — safe to call from a render loop.
        """
        if self.deadline is None:
            return
        if self._now() < self.deadline:
            return

        if self.state == GuardrailsState.COUNTDOWN:
            self.state = GuardrailsState.CHECKLIST
            self.deadline = None
        elif self.state in (
            GuardrailsState.LOSS_COOLDOWN,
            GuardrailsState.REARM_COOLDOWN,
            GuardrailsState.TRADE_COOLDOWN,
        ):
            self.state = GuardrailsState.ARMED
            self.deadline = None

    # ── User actions ───────────────────────────────────────────────────────

    def clock_in(self) -> bool:
        """Start the pre-trade countdown.  Returns True if accepted."""
        if self.state != GuardrailsState.CLOCKED_OUT:
            return False
        self.state = GuardrailsState.COUNTDOWN
        self.round_trips = 0
        self._set_deadline(self.config.clock_in_countdown_minutes * 60)
        return True

    def submit_checklist(self, answers: tuple[str, ...]) -> tuple[bool, str]:
        """Submit checklist answers.

        Returns (ok, reason).  On success advances to ARM_PROMPT and stores
        responses for journaling.
        """
        if self.state != GuardrailsState.CHECKLIST:
            return False, f"Not in checklist state (state={self.state.value})"
        if len(answers) != len(CHECKLIST_QUESTIONS):
            return False, (
                f"Expected {len(CHECKLIST_QUESTIONS)} answers, got {len(answers)}"
            )
        for i, a in enumerate(answers):
            if len(a.strip()) < MIN_RESPONSE_CHARS:
                return False, (
                    f"Answer {i + 1} must be at least {MIN_RESPONSE_CHARS} characters"
                )
        self.last_checklist = tuple(a.strip() for a in answers)
        self.state = GuardrailsState.ARM_PROMPT
        return True, ""

    def arm(self) -> bool:
        """Confirm the arm prompt; transitions to ARMED."""
        if self.state != GuardrailsState.ARM_PROMPT:
            return False
        self.state = GuardrailsState.ARMED
        return True

    def cancel(self) -> None:
        """Abort any pre-armed flow (countdown / checklist / arm prompt)."""
        if self.state in (
            GuardrailsState.COUNTDOWN,
            GuardrailsState.CHECKLIST,
            GuardrailsState.ARM_PROMPT,
            GuardrailsState.REARM_PROMPT,
        ):
            self.state = GuardrailsState.CLOCKED_OUT
            self.deadline = None

    def request_rearm(self, reason: str) -> tuple[bool, str]:
        """Submit the typed re-arm reason from GOAL_HIT.

        Returns (ok, reason).  On success transitions to REARM_COOLDOWN and
        stores the reason for journaling.
        """
        if self.state not in (GuardrailsState.GOAL_HIT, GuardrailsState.REARM_PROMPT):
            return False, f"Not in goal-hit state (state={self.state.value})"
        if len(reason.strip()) < MIN_RESPONSE_CHARS:
            return False, (
                f"Reason must be at least {MIN_RESPONSE_CHARS} characters"
            )
        self.last_rearm_reason = reason.strip()
        self.state = GuardrailsState.REARM_COOLDOWN
        self._set_deadline(self.config.rearm_cooldown_seconds)
        return True, ""

    def open_rearm_prompt(self) -> bool:
        """Move from GOAL_HIT into REARM_PROMPT (modal open)."""
        if self.state != GuardrailsState.GOAL_HIT:
            return False
        self.state = GuardrailsState.REARM_PROMPT
        return True

    def clock_out(self) -> None:
        """Reset to CLOCKED_OUT from any state.  Used on disconnect."""
        self.state = GuardrailsState.CLOCKED_OUT
        self.deadline = None
        self.round_trips = 0

    # ── Trader-driven notifications ────────────────────────────────────────

    def register_entry(self) -> None:
        """Notify that an entry order filled and position is now non-zero."""
        if self.state == GuardrailsState.ARMED:
            self.state = GuardrailsState.IN_POSITION

    def register_close(self, realized_points: float, cumulative_points: float) -> None:
        """Notify that a closing order filled and position is now flat.

        Increments the round-trip counter, then evaluates next state in
        priority order:
          1. round_trips ≥ max → MAX_TRADES_HIT (terminal)
          2. loss > threshold → LOSS_COOLDOWN
          3. cumulative ≥ daily goal → GOAL_HIT
          4. otherwise → TRADE_COOLDOWN
        """
        if self.state != GuardrailsState.IN_POSITION:
            return

        self.round_trips += 1

        if self.round_trips >= self.config.max_round_trips:
            self.state = GuardrailsState.MAX_TRADES_HIT
            self.deadline = None
            return

        if realized_points < -self.config.loss_cooldown_threshold:
            self.state = GuardrailsState.LOSS_COOLDOWN
            self._set_deadline(self.config.loss_cooldown_seconds)
            return

        if cumulative_points >= self.config.daily_goal:
            self.state = GuardrailsState.GOAL_HIT
            self.deadline = None
            return

        self.state = GuardrailsState.TRADE_COOLDOWN
        self._set_deadline(self.config.trade_cooldown_seconds)

    # ── Read-only views for the UI ─────────────────────────────────────────

    @property
    def entry_buttons_enabled(self) -> bool:
        return self.state == GuardrailsState.ARMED

    @property
    def flatten_enabled(self) -> bool:
        return self.state == GuardrailsState.IN_POSITION

    @property
    def show_clock_in_button(self) -> bool:
        return self.state == GuardrailsState.CLOCKED_OUT

    @property
    def show_rearm_button(self) -> bool:
        return self.state == GuardrailsState.GOAL_HIT

    @property
    def show_countdown(self) -> bool:
        return self.state in (
            GuardrailsState.COUNTDOWN,
            GuardrailsState.LOSS_COOLDOWN,
            GuardrailsState.REARM_COOLDOWN,
            GuardrailsState.TRADE_COOLDOWN,
        )
