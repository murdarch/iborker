"""IB connection management using ib_insync."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ib_insync import IB

from iborker.client_id import get_client_id, release_client_id
from iborker.config import IBSettings, settings


@asynccontextmanager
async def connect(
    tool: str = "cli",
    config: IBSettings | None = None,
) -> AsyncIterator[IB]:
    """Async context manager for IB connection.

    Args:
        tool: Tool identifier for client ID allocation (e.g., "history", "trader").
        config: Connection settings. Uses default settings if not provided.

    Yields:
        Connected IB instance.

    Example:
        async with connect("history") as ib:
            # Use ib for API calls
            pass
    """
    cfg = config or settings
    client_id = get_client_id(tool)
    ib = IB()

    try:
        await ib.connectAsync(
            host=cfg.host,
            port=cfg.port,
            clientId=client_id,
            timeout=cfg.timeout,
            readonly=cfg.readonly,
        )
        yield ib
    finally:
        ib.disconnect()
        release_client_id(tool)
