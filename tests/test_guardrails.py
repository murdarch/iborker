"""Tests for the guardrails-mode lifecycle."""

from __future__ import annotations

from datetime import UTC

from iborker.guardrails import (
    CHECKLIST_QUESTIONS,
    MIN_RESPONSE_CHARS,
    GuardrailsConfig,
    GuardrailsLifecycle,
    GuardrailsState,
)

# Long-enough placeholder strings for valid responses
GOOD_ANSWER = "x" * (MIN_RESPONSE_CHARS + 5)
SHORT_ANSWER = "too short"


def _config(
    *,
    daily_goal: float = 4.0,
    loss_threshold: float = 0.5,
    loss_seconds: int = 120,
    rearm_seconds: int = 300,
    countdown_minutes: int = 15,
) -> GuardrailsConfig:
    return GuardrailsConfig(
        daily_goal=daily_goal,
        loss_cooldown_threshold=loss_threshold,
        loss_cooldown_seconds=loss_seconds,
        rearm_cooldown_seconds=rearm_seconds,
        clock_in_countdown_minutes=countdown_minutes,
    )


def _arm(lc: GuardrailsLifecycle) -> None:
    """Run the full happy path up to ARMED."""
    assert lc.clock_in()
    # Force countdown deadline into the past so tick() advances us
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    assert lc.state == GuardrailsState.CHECKLIST
    ok, _ = lc.submit_checklist((GOOD_ANSWER,) * len(CHECKLIST_QUESTIONS))
    assert ok
    assert lc.state == GuardrailsState.ARM_PROMPT
    assert lc.arm()
    assert lc.state == GuardrailsState.ARMED


# ── Happy path ────────────────────────────────────────────────────────────


def test_clock_in_then_countdown():
    lc = GuardrailsLifecycle(config=_config())
    assert lc.state == GuardrailsState.CLOCKED_OUT
    assert lc.clock_in()
    assert lc.state == GuardrailsState.COUNTDOWN
    # Calling clock_in again is a no-op
    assert lc.clock_in() is False


def test_full_arming_flow():
    lc = GuardrailsLifecycle(config=_config())
    _arm(lc)


# ── Checklist validation ──────────────────────────────────────────────────


def test_checklist_rejects_short_answers():
    lc = GuardrailsLifecycle(config=_config())
    lc.clock_in()
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    answers = (GOOD_ANSWER, SHORT_ANSWER, GOOD_ANSWER)
    ok, reason = lc.submit_checklist(answers)
    assert not ok
    assert "20 characters" in reason
    assert lc.state == GuardrailsState.CHECKLIST


def test_checklist_rejects_wrong_count():
    lc = GuardrailsLifecycle(config=_config())
    lc.clock_in()
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    ok, _ = lc.submit_checklist((GOOD_ANSWER,))
    assert not ok


# ── In-position transitions ───────────────────────────────────────────────


def test_register_entry_moves_to_in_position():
    lc = GuardrailsLifecycle(config=_config())
    _arm(lc)
    lc.register_entry()
    assert lc.state == GuardrailsState.IN_POSITION


def test_register_close_winner_returns_to_armed():
    lc = GuardrailsLifecycle(config=_config(daily_goal=10.0))
    _arm(lc)
    lc.register_entry()
    # Profitable close, well under daily goal -> back to ARMED
    lc.register_close(realized_points=0.75, cumulative_points=0.75)
    assert lc.state == GuardrailsState.ARMED


# ── Loss cooldown ─────────────────────────────────────────────────────────


def test_loss_exceeds_threshold_triggers_cooldown():
    lc = GuardrailsLifecycle(config=_config(loss_threshold=0.5, loss_seconds=120))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=-0.75, cumulative_points=-0.75)
    assert lc.state == GuardrailsState.LOSS_COOLDOWN
    assert lc.remaining_seconds() > 0


def test_small_loss_does_not_trigger_cooldown():
    lc = GuardrailsLifecycle(config=_config(loss_threshold=0.5, daily_goal=10.0))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=-0.25, cumulative_points=-0.25)
    assert lc.state == GuardrailsState.ARMED


def test_loss_cooldown_expires_to_armed():
    lc = GuardrailsLifecycle(config=_config(loss_seconds=1))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=-1.0, cumulative_points=-1.0)
    assert lc.state == GuardrailsState.LOSS_COOLDOWN
    # Force deadline elapsed and tick
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    assert lc.state == GuardrailsState.ARMED


# ── Goal-hit re-arm ───────────────────────────────────────────────────────


def test_cumulative_at_goal_triggers_goal_hit():
    lc = GuardrailsLifecycle(config=_config(daily_goal=4.0))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=0.5, cumulative_points=4.25)
    assert lc.state == GuardrailsState.GOAL_HIT


def test_goal_hit_loss_threshold_takes_priority():
    """If a close is both a big loss and crosses goal, loss-cooldown wins."""
    # (Edge case: cumulative could cross goal with a small loss after big wins.
    # The rule is: loss-threshold check first, then goal check.)
    lc = GuardrailsLifecycle(config=_config(daily_goal=4.0, loss_threshold=0.5))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=-1.0, cumulative_points=4.0)
    assert lc.state == GuardrailsState.LOSS_COOLDOWN


def test_rearm_requires_long_reason():
    lc = GuardrailsLifecycle(config=_config(daily_goal=4.0))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=0.5, cumulative_points=4.5)
    assert lc.state == GuardrailsState.GOAL_HIT
    assert lc.open_rearm_prompt()
    ok, msg = lc.request_rearm("nope")
    assert not ok
    assert "20 characters" in msg


def test_rearm_then_cooldown_elapses_to_armed():
    lc = GuardrailsLifecycle(config=_config(daily_goal=4.0, rearm_seconds=1))
    _arm(lc)
    lc.register_entry()
    lc.register_close(realized_points=0.5, cumulative_points=4.5)
    lc.open_rearm_prompt()
    ok, _ = lc.request_rearm(GOOD_ANSWER)
    assert ok
    assert lc.state == GuardrailsState.REARM_COOLDOWN
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    assert lc.state == GuardrailsState.ARMED


# ── Disconnect / cancel ───────────────────────────────────────────────────


def test_clock_out_resets_from_any_state():
    lc = GuardrailsLifecycle(config=_config())
    _arm(lc)
    lc.register_entry()
    lc.clock_out()
    assert lc.state == GuardrailsState.CLOCKED_OUT
    assert lc.deadline is None


def test_cancel_during_checklist_returns_to_clocked_out():
    lc = GuardrailsLifecycle(config=_config())
    lc.clock_in()
    from datetime import datetime, timedelta

    lc.deadline = datetime.now(UTC) - timedelta(seconds=1)
    lc.tick()
    assert lc.state == GuardrailsState.CHECKLIST
    lc.cancel()
    assert lc.state == GuardrailsState.CLOCKED_OUT


# ── Settings validation ───────────────────────────────────────────────────


def test_guardrails_required_lists_missing(monkeypatch):
    for var in (
        "IB_DAILY_GOAL",
        "IB_LOSS_COOLDOWN_THRESHOLD",
        "IB_LOSS_COOLDOWN_SECONDS",
        "IB_REARM_COOLDOWN_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    from iborker.config import IBSettings

    # _env_file=None so the project's .env can't satisfy the check
    s = IBSettings(_env_file=None)
    missing = IBSettings.guardrails_required(s)
    assert set(missing) == {
        "IB_DAILY_GOAL",
        "IB_LOSS_COOLDOWN_THRESHOLD",
        "IB_LOSS_COOLDOWN_SECONDS",
        "IB_REARM_COOLDOWN_SECONDS",
    }


def test_guardrails_required_empty_when_set(monkeypatch):
    monkeypatch.setenv("IB_DAILY_GOAL", "4.0")
    monkeypatch.setenv("IB_LOSS_COOLDOWN_THRESHOLD", "0.5")
    monkeypatch.setenv("IB_LOSS_COOLDOWN_SECONDS", "120")
    monkeypatch.setenv("IB_REARM_COOLDOWN_SECONDS", "300")
    from iborker.config import IBSettings

    s = IBSettings(_env_file=None)
    assert IBSettings.guardrails_required(s) == []
