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

    # EWrapper and EClient must be real classes — TestConnection(EWrapper, EClient)
    # is defined at module level, and Python needs proper types to build the MRO.
    # Plain MagicMock() attributes cause a metaclass conflict.
    class _EWrapper:
        pass

    class _EClient:
        def __init__(self, wrapper: object = None) -> None:
            pass

    _wrapper_mod = MagicMock()
    _wrapper_mod.EWrapper = _EWrapper

    _client_mod = MagicMock()
    _client_mod.EClient = _EClient

    sys.modules["ibapi"] = MagicMock()
    sys.modules["ibapi.client"] = _client_mod
    sys.modules["ibapi.wrapper"] = _wrapper_mod
    sys.modules["ibapi.common"] = MagicMock()
    sys.modules["ibapi.contract"] = MagicMock()


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "live: requires a live TWS connection — skipped in CI"
    )
