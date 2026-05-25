import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "live: requires a live TWS connection — skipped in CI"
    )
