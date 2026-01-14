"""IB connection management using ib_insync."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ib_insync import IB

from iborker.config import IBSettings, settings


@asynccontextmanager
async def connect(
    config: IBSettings | None = None,
) -> AsyncIterator[IB]:
    """Async context manager for IB connection.

    Args:
        config: Connection settings. Uses default settings if not provided.

    Yields:
        Connected IB instance.

    Example:
        async with connect() as ib:
            # Use ib for API calls
            pass
    """
    cfg = config or settings
    ib = IB()

    try:
        await ib.connectAsync(
            host=cfg.host,
            port=cfg.port,
            clientId=cfg.client_id,
            timeout=cfg.timeout,
            readonly=cfg.readonly,
        )
        yield ib
    finally:
        ib.disconnect()
