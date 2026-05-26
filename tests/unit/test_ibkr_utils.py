from datetime import date as _real_date

import pytest
from hypothesis import given, strategies as st

from drafts.ibkr_utils import expiry_to_date, find_closest_expiry, find_closest_strike, print_data, valid_greek


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

    @given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False))
    def test_value_within_threshold_returns_value(self, value: float) -> None:
        assert valid_greek(value) == value

    @given(st.floats(allow_nan=False).filter(lambda x: abs(x) > 1e6))
    def test_value_exceeding_threshold_returns_none(self, value: float) -> None:
        assert valid_greek(value) is None

    @given(st.floats(min_value=1e6, max_value=2e6, allow_nan=False).filter(lambda x: abs(x) > 1e6))
    def test_value_just_above_threshold_returns_none(self, value: float) -> None:
        assert valid_greek(value) is None


class TestExpiryToDate:
    """Unit tests for expiry_to_date()."""

    def test_valid_date(self) -> None:
        assert expiry_to_date("20260516") == _real_date(2026, 5, 16)

    def test_jan_first(self) -> None:
        assert expiry_to_date("20260101") == _real_date(2026, 1, 1)

    def test_dec_last(self) -> None:
        assert expiry_to_date("20261231") == _real_date(2026, 12, 31)

    def test_leap_year_feb29(self) -> None:
        assert expiry_to_date("20240229") == _real_date(2024, 2, 29)

    def test_invalid_month_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("20261301")

    def test_invalid_day_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("20260230")  # Feb 30

    def test_non_leap_year_feb29_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("20250229")  # 2025 is not a leap year

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("2026AB16")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("")

    def test_too_short_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date("202605")

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError):
            expiry_to_date(None)  # type: ignore[arg-type]

    def test_extra_trailing_chars_ignored(self) -> None:
        # [6:9] on an 8-char string returns the same 2 chars as [6:8];
        # on a 9-char string it reads an extra char ("16X"), making int() fail on the mutant
        assert expiry_to_date("20260516X") == _real_date(2026, 5, 16)

    def test_error_message_includes_bad_input(self) -> None:
        # match uses re.search — anchor with ^ so "XXexpiry_to_date..." does not satisfy it
        with pytest.raises(ValueError, match=r"^expiry_to_date: could not parse"):
            expiry_to_date("BADSTRING")


class TestFindClosestExpiry:
    """Unit tests for find_closest_expiry()."""

    _TODAY = _real_date(2026, 5, 26)

    def _patch_today(self, mocker):  # type: ignore[no-untyped-def]
        mock = mocker.patch("drafts.ibkr_utils.date")
        mock.today.return_value = self._TODAY
        mock.side_effect = _real_date
        return mock

    def test_empty_set_returns_none(self, mocker) -> None:
        self._patch_today(mocker)
        assert find_closest_expiry(set(), 7) is None

    def test_all_expired_returns_none(self, mocker) -> None:
        self._patch_today(mocker)
        # Both dates are before 2026-05-26 (DTE < 0)
        assert find_closest_expiry({"20260520", "20260525"}, 7) is None

    def test_single_future_entry(self, mocker) -> None:
        self._patch_today(mocker)
        # 20260602: DTE = 7 from 2026-05-26
        assert find_closest_expiry({"20260602"}, 7) == "20260602"

    def test_exact_target_dte_wins(self, mocker) -> None:
        self._patch_today(mocker)
        # 20260602 DTE=7 (distance 0) beats 20260609 DTE=14 (distance 7)
        result = find_closest_expiry({"20260602", "20260609"}, 7)
        assert result == "20260602"

    def test_closest_of_two(self, mocker) -> None:
        self._patch_today(mocker)
        # 20260530 DTE=4 (distance 3) beats 20260609 DTE=14 (distance 7)
        result = find_closest_expiry({"20260530", "20260609"}, 7)
        assert result == "20260530"

    def test_malformed_entry_skipped(self, mocker) -> None:
        self._patch_today(mocker)
        result = find_closest_expiry({"BADENTRY", "20260602"}, 7)
        assert result == "20260602"

    def test_expired_entry_skipped(self, mocker) -> None:
        self._patch_today(mocker)
        # 20260520 DTE=-6 is expired; only 20260602 qualifies
        result = find_closest_expiry({"20260520", "20260602"}, 7)
        assert result == "20260602"

    def test_iteration_continues_after_expired_entry(self, mocker) -> None:
        # mutant #27: continue → break in the expired-entry block stops processing early;
        # a list guarantees the expired entry is iterated first so break is observable
        self._patch_today(mocker)
        assert find_closest_expiry(["20260520", "20260602"], 7) == "20260602"

    def test_today_expiry_valid(self, mocker) -> None:
        self._patch_today(mocker)
        # DTE=0 is not expired (condition is dte < 0)
        assert find_closest_expiry({"20260526"}, 0) == "20260526"

    def test_malformed_entry_prints_warning(self, mocker, capsys) -> None:
        # mutant #21 wraps the warning in "XX...XX"; the substring check passes for the mutant
        # because "find_closest_expiry:..." still appears inside "XXfind_closest_expiry:...XX";
        # asserting "XX" is absent makes the wrapping observable
        self._patch_today(mocker)
        find_closest_expiry({"BADENTRY", "20260602"}, 7)
        out = capsys.readouterr().out
        assert "find_closest_expiry: skipping bad expiry string" in out
        assert "XX" not in out

    def test_iteration_continues_after_bad_entry(self, mocker) -> None:
        # mutant #22 turns `continue` into `break`, stopping after the first bad entry;
        # a list (not a set) guarantees BADENTRY is iterated first so break is observable
        self._patch_today(mocker)
        assert find_closest_expiry(["BADENTRY", "20260602"], 7) == "20260602"

    def test_distance_is_abs_dte_minus_target(self, mocker) -> None:
        # mutant #28: abs(dte + target_dte) instead of abs(dte - target_dte) swaps the winner
        # today=2026-05-26, target=7
        # 20260529 DTE=3: |3-7|=4  vs  |3+7|=10  (mutant)
        # 20260604 DTE=9: |9-7|=2  vs  |9+7|=16  (mutant) → mutant picks 20260529
        self._patch_today(mocker)
        assert find_closest_expiry({"20260529", "20260604"}, 7) == "20260604"

    def test_first_equal_distance_wins(self, mocker) -> None:
        # mutant #30: <= instead of < causes the last equal-distance entry to replace the first;
        # a list fixes iteration order so the outcome is deterministic
        # 2026-05-29 DTE=3 and 2026-06-06 DTE=11 both have distance 4 from target_dte=7
        self._patch_today(mocker)
        assert find_closest_expiry(["20260529", "20260606"], 7) == "20260529"


class TestFindClosestStrike:
    """Unit tests for find_closest_strike()."""

    def test_empty_set_returns_none(self) -> None:
        assert find_closest_strike(set(), 100.0) is None

    def test_single_strike(self) -> None:
        assert find_closest_strike({200.0}, 100.0) == 200.0

    def test_exact_match(self) -> None:
        assert find_closest_strike({95.0, 100.0, 105.0}, 100.0) == 100.0

    def test_below_all_strikes(self) -> None:
        assert find_closest_strike({100.0, 105.0, 110.0}, 90.0) == 100.0

    def test_above_all_strikes(self) -> None:
        assert find_closest_strike({90.0, 95.0, 100.0}, 110.0) == 100.0

    def test_closer_to_lower(self) -> None:
        assert find_closest_strike({100.0, 110.0}, 102.0) == 100.0

    def test_closer_to_upper(self) -> None:
        assert find_closest_strike({100.0, 110.0}, 108.0) == 110.0

    @given(
        und_price=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
    )
    def test_result_always_in_strikes(self, und_price: float) -> None:
        strikes = {95.0, 100.0, 105.0, 110.0}
        result = find_closest_strike(strikes, und_price)
        assert result in strikes

    def test_first_equal_distance_wins(self) -> None:
        # mutant #38: <= instead of < causes the last equal-distance strike to replace the first;
        # a list fixes iteration order — 100.0 and 110.0 are equidistant from 105.0
        assert find_closest_strike([100.0, 110.0], 105.0) == 100.0


class TestPrintData:
    """Unit tests for print_data()."""

    def test_symbol_in_output(self, capsys) -> None:
        print_data("IWM", "20260516", 220.0, {}, {})
        assert "IWM" in capsys.readouterr().out

    def test_expiry_in_output(self, capsys) -> None:
        print_data("IWM", "20260516", 220.0, {}, {})
        assert "20260516" in capsys.readouterr().out

    def test_call_and_put_labels_present(self, capsys) -> None:
        print_data("SPY", "20260620", 580.0, {}, {})
        captured = capsys.readouterr().out
        assert "CALL" in captured
        assert "PUT" in captured

    def test_call_and_put_label_exact_format(self, capsys) -> None:
        # #46/#47: "XXCALLXX"/"XXPUTXX" still contain "CALL"/"PUT" so the old test misses them;
        #          checking the label directly adjacent to "bid=" catches the mutation
        # #48: wrapping the label in "XX  CALLXX" breaks the "  CALL  bid=" adjacency
        # #51,#54,#57,#60,#63,#66,#69: each field wrapped in "XX...XX" inserts "XX" between
        #          neighbouring fields — "XX" must never appear in clean output
        print_data("SPY", "20260620", 580.0, {}, {})
        out = capsys.readouterr().out
        assert "  CALL  bid=" in out
        assert "  PUT  bid=" in out
        assert "XX" not in out

    def test_missing_keys_do_not_raise(self, capsys) -> None:
        print_data("SPY", "20260620", 580.0, {}, {})
        capsys.readouterr()

    def test_none_values_do_not_raise(self, capsys) -> None:
        call_data: dict[str, float | None] = {"bid": None, "delta": None}
        print_data("SPY", "20260620", 580.0, call_data, {})
        capsys.readouterr()

    def test_actual_values_rendered(self, capsys) -> None:
        # #43: data.get(key) → None makes every field show 0.0 — real values must appear
        # #49,#52,#55,#58,#61,#64,#67: wrong key names (e.g. "XXbidXX") miss the real key,
        #   falling back to 0.0 — each field's expected value must be present in output
        call_data: dict[str, float | None] = {
            "bid": 1.23, "ask": 4.56, "iv": 0.25,
            "delta": 0.43, "gamma": 0.02, "theta": -0.05, "vega": 0.12,
        }
        print_data("SPY", "20260620", 580.0, call_data, {})
        out = capsys.readouterr().out
        for expected in ["1.23", "4.56", "0.25", "0.43", "0.02", "-0.05", "0.12"]:
            assert expected in out

    def test_missing_keys_default_to_zero(self, capsys) -> None:
        # #45: fallback 0.0 → 1.0 — "assert '0.0' in out" is not enough because the strike
        # "580.0" already contains "0.0" as a substring; checking "1.0" is absent is unambiguous
        print_data("SPY", "20260620", 580.0, {}, {})
        out = capsys.readouterr().out
        assert "1.0" not in out

    def test_header_format(self, capsys) -> None:
        # #42: mutant wraps the whole header in "XX...XX", breaking the "\n---" prefix
        # #41: mutant corrupts the strftime format to "XX%H:%M:%SXX", breaking HH:MM:SS shape
        import re
        print_data("IWM", "20260516", 220.0, {}, {})
        out = capsys.readouterr().out
        assert "\n---" in out
        assert re.search(r'\(\d{2}:\d{2}:\d{2}\)', out)

    def test_bid_ask_precision_two_decimals(self, capsys) -> None:
        # #50,#53: digits 2→3 changes rounding — round(1.234,2)=1.23, round(1.234,3)=1.234
        call_data: dict[str, float | None] = {"bid": 1.234, "ask": 1.566}
        print_data("SPY", "20260620", 580.0, call_data, {})
        out = capsys.readouterr().out
        assert "1.23" in out
        assert "1.57" in out
        assert "1.234" not in out
        assert "1.566" not in out

    def test_greek_precision_four_decimals(self, capsys) -> None:
        # #56,#59,#62,#65,#68: digits 4→5 changes rounding —
        # round(0.12346,4)=0.1235, round(0.12346,5)=0.12346
        call_data: dict[str, float | None] = {
            "iv": 0.12346, "delta": 0.45556, "gamma": 0.12346,
            "theta": -0.12346, "vega": 0.12346,
        }
        print_data("SPY", "20260620", 580.0, call_data, {})
        out = capsys.readouterr().out
        assert "0.1235" in out
        assert "0.4556" in out
        assert "0.12346" not in out
        assert "0.45556" not in out

    def test_full_data_renders(self, capsys) -> None:
        call_data: dict[str, float | None] = {
            "bid": 1.5, "ask": 1.6, "iv": 0.25,
            "delta": 0.45, "gamma": 0.02, "theta": -0.05, "vega": 0.15,
        }
        put_data: dict[str, float | None] = {
            "bid": 1.4, "ask": 1.5, "iv": 0.24,
            "delta": -0.55, "gamma": 0.02, "theta": -0.04, "vega": 0.14,
        }
        print_data("SPY", "20260620", 580.0, call_data, put_data)
        captured = capsys.readouterr().out
        assert "CALL" in captured
        assert "PUT" in captured
