"""Trading guards – time gates and calendar awareness.

Prevents impulsive trading during the opening chaos and when the
trader has a meeting about to interrupt their focus.
"""

import subprocess
import sys
from datetime import datetime, time, timedelta, timezone

from iborker.config import settings


# ── Configuration (override via IB_ env vars or config.yaml later) ──────────────

# Earliest time (ET) that trade buttons become enabled.
TRADING_START_ET: time = time(9, 45)

# If a meeting is within this many minutes, show a warning banner.
MEETING_PROXIMITY_MINUTES = 15


# ── Time gate ──────────────────────────────────────────────────────────────────

def _et_now() -> datetime:
    """Return current time in US Eastern (auto handles EST/EDT)."""
    # Use system timezone if ET, otherwise convert.
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        # Python < 3.9 fallback
        from backports.zoneinfo import ZoneInfo  # type: ignore
        tz = ZoneInfo("America/New_York")  # type: ignore
    return datetime.now(tz)


def trading_window_open() -> bool:
    """Return True if the current ET time is at or after TRADING_START_ET."""
    return _et_now().time() >= TRADING_START_ET


# ── Calendar gate (org-mode / Outlook) ─────────────────────────────────────────

def _parse_org_calendar() -> list[datetime]:
    """Parse upcoming appointments from the user's org-mode calendar file.

    Looks for the file at the path given by IB_ORG_CAL_PATH env var,
    falling back to ~/org/trading.org and ~/org/agenda.org.

    Returns a list of appointment start datetimes (timezone-aware, ET).
    """
    import os
    import re
    from pathlib import Path

    cal_path = os.environ.get(
        "IB_ORG_CAL_PATH",
        str(Path.home() / "org" / "agenda.org"),
    )

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore
        tz = ZoneInfo("America/New_York")  # type: ignore

    path = Path(cal_path)
    if not path.exists():
        return []

    appointments: list[datetime] = []
    # Match org-mode timestamp entries like:
    #   [2026-04-25 Sat 10:30]
    #   <2026-04-25 Sat 14:00--15:00>
    ts_re = re.compile(
        r"[\[<](\d{4}-\d{2}-\d{2})\s+\w+\s+(\d{2}:\d{2})",
    )

    with open(path) as f:
        for line in f:
            m = ts_re.search(line)
            if m:
                date_str, time_str = m.groups()
                try:
                    dt = datetime.strptime(
                        f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=tz)
                    appointments.append(dt)
                except ValueError:
                    pass

    return appointments


def _check_outlook_calendar() -> list[datetime]:
    """Use org-mode's Outlook sync output if available.

    On WSL this reads the org file that has already been synced from
    Outlook.  On native Windows you could call Outlook COM directly,
    but that's overkill since the org file is the source of truth.
    """
    return _parse_org_calendar()


def _get_upcoming_meetings() -> list[datetime]:
    """Return list of upcoming meeting start times (ET-aware datetimes)."""
    return _check_outlook_calendar()


def meeting_soon() -> tuple[bool, str]:
    """Check if there's a meeting within MEETING_PROXIMITY_MINUTES.

    Returns (is_close, message).
    """
    now = _et_now()
    meetings = _get_upcoming_meetings()

    for mt in sorted(meetings):
        delta = mt - now
        if timedelta(0) < delta < timedelta(minutes=MEETING_PROXIMITY_MINUTES):
            mins = int(delta.total_seconds() / 60)
            return True, f"Meeting in {mins}min ({mt.strftime('%H:%M')} ET)"
        if delta < timedelta(0):
            continue  # past meeting, keep looking

    return False, ""


# ── Combined guard ─────────────────────────────────────────────────────────────

class TradingGuard:
    """Stateless guard that answers whether trading is allowed."""

    def __init__(self) -> None:
        self._last_check: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._cached_allowed = True
        self._cached_reason = ""

    def check(self) -> tuple[bool, str]:
        """Return (allowed, reason).

        Re-checks at most once per second to avoid perf hit on every tick.
        """
        now_utc = datetime.now(timezone.utc)
        if (now_utc - self._last_check).total_seconds() < 1.0:
            return self._cached_allowed, self._cached_reason

        self._last_check = now_utc

        if not trading_window_open():
            et = _et_now().strftime("%H:%M")
            reason = f"Trading disabled until {TRADING_START_ET.strftime('%H:%M')} ET (now {et})"
            self._cached_allowed = False
            self._cached_reason = reason
            return False, reason

        soon, msg = meeting_soon()
        if soon:
            self._cached_allowed = False
            self._cached_reason = msg
            return False, msg

        self._cached_allowed = True
        self._cached_reason = ""
        return True, ""
