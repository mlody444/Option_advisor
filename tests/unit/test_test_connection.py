import pytest
from hypothesis import given, settings, strategies as st

from drafts.ibkr_utils import valid_greek


class TestValidGreek:
    """Unit tests for valid_greek()."""

    def test_none_returns_none(self) -> None:
        assert valid_greek(None) is None

    def test_nan_returns_none(self) -> None:
        assert valid_greek(float("nan")) is None

    def test_positive_infinity_returns_none(self) -> None:
        assert valid_greek(float("inf")) is None

    def test_negative_infinity_returns_none(self) -> None:
        assert valid_greek(float("-inf")) is None

    def test_value_at_threshold_boundary(self) -> None:
        assert valid_greek(1e6) == 1e6              # exactly at threshold — must pass through
        assert valid_greek(-1e6) == -1e6            # negative mirror
        assert valid_greek(1_000_000.001) is None   # just above threshold
        assert valid_greek(-1_000_000.001) is None  # negative mirror
        assert valid_greek(1_000_001.0) is None     # clearly above threshold
        assert valid_greek(-1_000_001.0) is None    # negative mirror
        assert valid_greek(1_500_000.0) is None     # midpoint between 1e6 and 2e6
        assert valid_greek(-1_500_000.0) is None    # negative mirror

    @settings(max_examples=25)
    @given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False))
    def test_value_within_threshold_returns_value(self, value: float) -> None:
        assert valid_greek(value) == value

    @settings(max_examples=25)
    @given(st.floats(allow_nan=False).filter(lambda x: abs(x) > 1e6))
    def test_value_exceeding_threshold_returns_none(self, value: float) -> None:
        assert valid_greek(value) is None

    @settings(max_examples=25)
    @given(st.floats(min_value=1e6, max_value=2e6, allow_nan=False).filter(lambda x: abs(x) > 1e6))
    def test_value_just_above_threshold_returns_none(self, value: float) -> None:
        assert valid_greek(value) is None
