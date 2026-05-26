import sys

import pytest

try:
    import ibapi  # noqa: F401
except ImportError:
    from unittest.mock import MagicMock

    sys.modules["ibapi"] = MagicMock()
    sys.modules["ibapi.client"] = MagicMock()
    sys.modules["ibapi.wrapper"] = MagicMock()
    sys.modules["ibapi.common"] = MagicMock()
    sys.modules["ibapi.contract"] = MagicMock()


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "live: requires a live TWS connection — skipped in CI"
    )
