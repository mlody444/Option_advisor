"""Integration tests for TestConnection callbacks (SWE.5 — Software Integration Test).

Tests the boundary between ibapi callbacks and TestConnection state management,
and the boundary between TestConnection state and ibkr_utils functions.
ibapi is mocked via conftest.py; callbacks are exercised directly without a live
TWS connection.

Flow covered:
    TestConnectFlow       → connectAck sets connected event
    TestContractIdFlow    → contractDetails + contractDetailsEnd interaction and late-callback guard
    TestOptionChainFlow   → secDefOptParam accumulation → find_closest_expiry / find_closest_strike
    TestGreekStreamingFlow → tickPrice + tickOptionComputation → call_data / put_data → print_data
"""

from typing import ClassVar
from unittest.mock import MagicMock

from drafts.ibkr_utils import find_closest_expiry, find_closest_strike, print_data
from drafts.test_connection import (
    REQ_CALL,
    REQ_CONTRACT_DETAILS,
    REQ_OPT_PARAMS,
    REQ_PUT,
    REQ_UNDERLYING,
    TestConnection,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def make_app() -> TestConnection:
    """Return a freshly initialised TestConnection with no ibapi connection."""
    return TestConnection()


def make_contract_details(con_id: int) -> MagicMock:
    """Return a mock ContractDetails whose .contract.conId equals con_id."""
    details = MagicMock()
    details.contract.conId = con_id
    return details


# ── TestConnectFlow ───────────────────────────────────────────────────────────


class TestConnectFlow:
    """connectAck() transitions the connected event from clear to set."""

    def test_pos_connectack_sets_connected(self) -> None:
        # step 1: fresh instance — event must be clear before ibapi fires
        app = make_app()
        assert not app.connected.is_set()

        # step 2: ibapi fires connectAck — main thread can now proceed past .wait()
        app.connectAck()
        assert app.connected.is_set()


# ── TestContractIdFlow ────────────────────────────────────────────────────────


class TestContractIdFlow:
    """contractDetails() + contractDetailsEnd() manage the underlying conId.

    Positive path: valid conId stored and contract_id_ready set together —
    main thread can proceed with a non-None conId (invariant).
    Negative paths: duplicate contractDetails dropped; late callback after End
    discarded so main() can detect the missing conId.
    """

    def test_pos_valid_details_then_end_stores_con_id_and_sets_event(self) -> None:
        # step 1: fresh instance — conId absent, event clear
        app = make_app()
        assert app.underlying_con_id is None
        assert not app.contract_id_ready.is_set()

        # step 2: ibapi delivers valid contract details
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))

        # step 3: ibapi signals end of results — main thread unblocked
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)

        # invariant: when event is set, conId must be non-None
        assert app.contract_id_ready.is_set()
        assert app.underlying_con_id == 12345

    def test_neg_second_details_before_end_does_not_overwrite_first(self) -> None:
        # step 1: first valid result arrives
        app = make_app()
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))

        # step 2: ibapi delivers a second result (ambiguous symbol returns multiple)
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(99999))

        # step 3: End fires — first conId must be preserved
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)
        assert app.underlying_con_id == 12345

    def test_neg_late_callback_after_end_is_discarded(self) -> None:
        # step 1: End fires first (ibapi returned no results for the symbol)
        app = make_app()
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)
        assert app.contract_id_ready.is_set()
        assert app.underlying_con_id is None

        # step 2: late contractDetails arrives after End
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))

        # late callback discarded — conId stays None so main() can detect the failure
        assert app.underlying_con_id is None

    def test_neg_invalid_details_then_end_leaves_con_id_none(self) -> None:
        # step 1: ibapi returns details but with no usable conId (None payload)
        app = make_app()
        app.contractDetails(REQ_CONTRACT_DETAILS, None)
        assert app.underlying_con_id is None

        # step 2: End fires normally — event gets set
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)

        # event is set but conId is None — main() checks this and returns with an error
        assert app.contract_id_ready.is_set()
        assert app.underlying_con_id is None

    def test_neg_zero_con_id_then_end_leaves_con_id_none(self) -> None:
        # step 1: ibapi returns details with conId=0 — ambiguous contract, unusable
        app = make_app()
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(0))
        assert app.underlying_con_id is None

        # step 2: End fires normally
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)

        # event is set but conId is None — same failure mode as None payload
        assert app.contract_id_ready.is_set()
        assert app.underlying_con_id is None

    def test_neg_none_inner_contract_then_end_leaves_con_id_none(self) -> None:
        # step 1: ibapi returns a details object whose .contract attribute is None
        app = make_app()
        details = MagicMock()
        details.contract = None
        app.contractDetails(REQ_CONTRACT_DETAILS, details)
        assert app.underlying_con_id is None

        # step 2: End fires normally
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)

        # event is set but conId is None — same failure mode
        assert app.contract_id_ready.is_set()
        assert app.underlying_con_id is None


# ── TestOptionChainFlow ───────────────────────────────────────────────────────


class TestOptionChainFlow:
    """secDefOptParam callbacks accumulate option chain data consumed by ibkr_utils.

    Module boundary crossed:
        TestConnection.available_expirations → find_closest_expiry()
        TestConnection.available_strikes + und_price → find_closest_strike()

    Expiry dates are built relative to today so no date-mocking is needed.
    """

    def test_pos_smart_params_enable_target_contract_selection(self) -> None:
        from datetime import date, timedelta

        today = date.today()
        expiry_7dte = (today + timedelta(days=7)).strftime("%Y%m%d")
        expiry_30dte = (today + timedelta(days=30)).strftime("%Y%m%d")

        # step 1: underlying price arrives via tickPrice
        app = make_app()
        app.tickPrice(REQ_UNDERLYING, 4, 200.0, MagicMock())
        assert app.und_price == 200.0

        # step 2: ibapi delivers SMART option chain — expirations and strikes
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "SMART", 0, "", "",
            {expiry_7dte, expiry_30dte}, {195.0, 200.0, 205.0},
        )

        # step 3: End fires — data is fully populated and params_ready is set
        app.securityDefinitionOptionParameterEnd(REQ_OPT_PARAMS)
        assert app.params_ready.is_set()

        # step 4: ibkr_utils selects target contract from callback-collected state
        expiry = find_closest_expiry(app.available_expirations, 7)
        strike = find_closest_strike(app.available_strikes, app.und_price)  # type: ignore[arg-type]
        assert expiry == expiry_7dte
        assert strike == 200.0

    def test_neg_non_smart_data_excluded_from_selection(self) -> None:
        from datetime import date, timedelta

        today = date.today()
        expiry_7dte = (today + timedelta(days=7)).strftime("%Y%m%d")

        # step 1: only CBOE data arrives — SMART filter must block it
        app = make_app()
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "CBOE", 0, "", "",
            {expiry_7dte}, {200.0},
        )
        app.securityDefinitionOptionParameterEnd(REQ_OPT_PARAMS)
        assert app.params_ready.is_set()

        # step 2: available sets are empty — ibkr_utils returns None for both
        assert find_closest_expiry(app.available_expirations, 7) is None
        assert find_closest_strike(app.available_strikes, 200.0) is None

    def test_neg_mixed_exchanges_only_smart_data_used(self) -> None:
        from datetime import date, timedelta

        today = date.today()
        expiry_smart = (today + timedelta(days=7)).strftime("%Y%m%d")
        expiry_cboe = (today + timedelta(days=14)).strftime("%Y%m%d")

        # step 1: SMART and CBOE both deliver data
        app = make_app()
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "SMART", 0, "", "",
            {expiry_smart}, {200.0},
        )
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "CBOE", 0, "", "",
            {expiry_cboe}, {195.0},
        )
        app.securityDefinitionOptionParameterEnd(REQ_OPT_PARAMS)

        # step 2: only SMART expiry and strike are in the available sets
        assert expiry_smart in app.available_expirations
        assert expiry_cboe not in app.available_expirations
        assert 200.0 in app.available_strikes
        assert 195.0 not in app.available_strikes

    def test_pos_multiple_smart_calls_accumulate_for_selection(self) -> None:
        from datetime import date, timedelta

        today = date.today()
        expiry_7dte = (today + timedelta(days=7)).strftime("%Y%m%d")
        expiry_30dte = (today + timedelta(days=30)).strftime("%Y%m%d")

        # step 1: ibapi fires SMART twice — different trading classes, each with partial data
        app = make_app()
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "SMART", 0, "", "",
            {expiry_7dte}, {195.0, 200.0},
        )
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "SMART", 0, "", "",
            {expiry_30dte}, {200.0, 205.0},
        )

        # step 2: End fires — all SMART data from both calls must be accumulated
        app.securityDefinitionOptionParameterEnd(REQ_OPT_PARAMS)
        assert app.params_ready.is_set()

        # step 3: ibkr_utils sees the full accumulated set, not just the last delivery
        expiry = find_closest_expiry(app.available_expirations, 7)
        strike = find_closest_strike(app.available_strikes, 202.0)
        assert expiry == expiry_7dte
        assert strike == 200.0


# ── TestGreekStreamingFlow ────────────────────────────────────────────────────


class TestGreekStreamingFlow:
    """tickPrice + tickOptionComputation populate call_data/put_data consumed by print_data.

    Module boundary crossed:
        tickPrice → call_data / put_data (prices)
        tickOptionComputation → valid_greek() → call_data / put_data (Greeks)
        call_data / put_data → print_data()
    """

    _GREEK_DEFAULTS: ClassVar[dict[str, object]] = dict(
        tick_type=13, _tick_attrib=0,
        implied_vol=0.25, delta=0.45, _opt_price=1.5, _pv_dividend=0.0,
        gamma=0.02, vega=0.15, theta=-0.05, _und_price=200.0,
    )

    def _fire_greeks(self, app: TestConnection, req_id: int, **overrides: object) -> None:
        app.tickOptionComputation(req_id, **{**self._GREEK_DEFAULTS, **overrides})  # type: ignore[arg-type]

    def test_pos_prices_and_greeks_flow_into_print_data(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: price ticks arrive for the call
        app = make_app()
        app.tickPrice(REQ_CALL, 1, 1.50, MagicMock())  # bid
        app.tickPrice(REQ_CALL, 2, 1.60, MagicMock())  # ask

        # step 2: Greek tick arrives (tick_type 13 = model price)
        self._fire_greeks(app, REQ_CALL)

        # step 3: ibkr_utils renders the fully populated call_data
        print_data("IWM", "20991231", 200.0, app.call_data, {})
        out = capsys.readouterr().out
        assert "1.5" in out   # bid
        assert "1.6" in out   # ask
        assert "0.45" in out  # delta
        assert "0.25" in out  # iv

    def test_pos_call_and_put_rendered_independently(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: call prices and greeks
        app = make_app()
        app.tickPrice(REQ_CALL, 1, 1.50, MagicMock())
        self._fire_greeks(app, REQ_CALL, delta=0.45)

        # step 2: put prices and greeks — different values, different req_id
        app.tickPrice(REQ_PUT, 1, 1.40, MagicMock())
        self._fire_greeks(app, REQ_PUT, delta=-0.55)

        # step 3: print_data renders both sides without cross-contamination
        print_data("IWM", "20991231", 200.0, app.call_data, app.put_data)
        out = capsys.readouterr().out
        assert "0.45" in out   # call delta
        assert "-0.55" in out  # put delta

    def test_neg_invalid_greeks_render_as_zero_in_print_data(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: tickOptionComputation arrives with NaN delta and sentinel iv
        app = make_app()
        self._fire_greeks(app, REQ_CALL, delta=float("nan"), implied_vol=2e6)

        # step 2: valid_greek() stored None for both invalid values
        assert app.call_data["delta"] is None
        assert app.call_data["iv"] is None

        # step 3: print_data must not raise and must render None as 0, not "nan"/"None"
        print_data("IWM", "20991231", 200.0, app.call_data, {})
        out = capsys.readouterr().out
        assert "nan" not in out
        assert "None" not in out

    def test_neg_later_price_tick_overwrites_earlier(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: initial bid arrives
        app = make_app()
        app.tickPrice(REQ_CALL, 1, 1.50, MagicMock())

        # step 2: updated bid arrives — price moved
        app.tickPrice(REQ_CALL, 1, 1.75, MagicMock())

        # step 3: print_data must show the latest value, not the first
        print_data("IWM", "20991231", 200.0, app.call_data, {})
        out = capsys.readouterr().out
        assert "1.75" in out
