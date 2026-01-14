"""Client ID allocation for IB connections.

Manages unique client IDs to prevent connection conflicts when multiple
iborker tools run concurrently.
"""

import atexit
import os
import signal
from pathlib import Path

from iborker.config import settings

# Tool type to offset mapping
# Each tool type gets a reserved range of 10 IDs
TOOL_OFFSETS = {
    "cli": 0,  # CLI commands: base + 0-9
    "history": 0,
    "contracts": 0,
    "trader": 10,  # Click Trader: base + 10-19
    "stdev": 20,  # Stdev Analyzer: base + 20-29
    # Reserved for future: 30+
}

# Range size per tool type
RANGE_SIZE = 10

# Lock directory
LOCK_DIR = Path.home() / ".iborker" / "locks"


def _get_lock_path(client_id: int) -> Path:
    """Get lock file path for a client ID."""
    return LOCK_DIR / f"client_{client_id}.lock"


def _acquire_lock(client_id: int) -> bool:
    """Try to acquire a lock for the given client ID.

    Returns True if lock acquired, False if already locked.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _get_lock_path(client_id)

    try:
        # Use O_CREAT | O_EXCL for atomic creation
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Check if the process holding the lock is still alive
        try:
            with open(lock_path) as f:
                pid = int(f.read().strip())
            # Check if process exists
            os.kill(pid, 0)
            return False  # Process still alive, lock is valid
        except (ValueError, ProcessLookupError, PermissionError):
            # Process doesn't exist or invalid PID, remove stale lock
            try:
                lock_path.unlink()
                return _acquire_lock(client_id)  # Retry
            except OSError:
                return False


def _release_lock(client_id: int) -> None:
    """Release a lock for the given client ID."""
    lock_path = _get_lock_path(client_id)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


class ClientIdManager:
    """Manages client ID allocation for a tool."""

    def __init__(self, tool: str):
        self.tool = tool
        self.client_id: int | None = None
        self._cleanup_registered = False

    def allocate(self) -> int:
        """Allocate a unique client ID for this tool.

        Returns the allocated client ID.
        """
        if settings.client_id_mode == "fixed":
            return settings.client_id

        base = settings.client_id_start
        offset = TOOL_OFFSETS.get(self.tool, 0)

        # Try each ID in the tool's range
        for i in range(RANGE_SIZE):
            candidate = base + offset + i
            if _acquire_lock(candidate):
                self.client_id = candidate
                self._register_cleanup()
                return candidate

        # All IDs in range exhausted, use a high ID as fallback
        # This shouldn't happen in normal usage
        fallback = base + offset + 100 + os.getpid() % 100
        self.client_id = fallback
        return fallback

    def release(self) -> None:
        """Release the allocated client ID."""
        if self.client_id is not None:
            _release_lock(self.client_id)
            self.client_id = None

    def _register_cleanup(self) -> None:
        """Register cleanup handlers for process exit."""
        if self._cleanup_registered:
            return

        atexit.register(self.release)

        # Handle common signals
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                original = signal.getsignal(sig)

                def handler(signum, frame, orig=original):
                    self.release()
                    if callable(orig):
                        orig(signum, frame)
                    elif orig == signal.SIG_DFL:
                        signal.signal(signum, signal.SIG_DFL)
                        os.kill(os.getpid(), signum)

                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass  # Signal handling not available

        self._cleanup_registered = True


# Module-level manager instances per tool
_managers: dict[str, ClientIdManager] = {}


def get_client_id(tool: str) -> int:
    """Get a unique client ID for the specified tool.

    Args:
        tool: Tool identifier (e.g., "history", "trader", "stdev")

    Returns:
        Allocated client ID.
    """
    if tool not in _managers:
        _managers[tool] = ClientIdManager(tool)
    return _managers[tool].allocate()


def release_client_id(tool: str) -> None:
    """Release the client ID for the specified tool.

    Args:
        tool: Tool identifier.
    """
    if tool in _managers:
        _managers[tool].release()
        del _managers[tool]
