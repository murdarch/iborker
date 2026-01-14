"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def ib_settings():
    """Provide test IB settings."""
    from iborker.config import IBSettings

    return IBSettings(
        host="127.0.0.1",
        port=7497,
        client_id=999,  # Use high client ID for tests
        timeout=5.0,
        readonly=True,
    )
