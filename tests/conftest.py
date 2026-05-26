import os
import sys

import pytest
from hypothesis import settings

settings.register_profile("ci", max_examples=50)
settings.register_profile("local", max_examples=10)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "local"))

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
