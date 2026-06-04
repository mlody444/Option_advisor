"""Unit tests for TestConnection callback guards (SWE.4 — Software Unit Verification).

Each test exercises a single callback method in isolation, verifying guard
conditions and routing logic. Multi-step flows and ibkr_utils boundaries are
covered in tests/integration/test_test_connection.py.

ibapi is mocked via conftest.py; no TWS connection is needed.
"""

import logging
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from drafts.test_connection import (
    KNOWN_ERRORS,
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


# ── TestConnectAckCallback ────────────────────────────────────────────────────


class TestConnectAckCallback:
    """Guard conditions for connectAck(), nextValidId(), and connectionClosed()."""

    def test_pos_connectack_sets_connected(self) -> None:
        # step 1: fresh instance — connected event clear
        app = make_app()
        assert not app.connected.is_set()

        # step 2: ibapi fires connectAck
        app.connectAck()

        # step 3: event set — main thread can proceed past .wait()
        assert app.connected.is_set()

    def test_pos_nextvalidid_sets_ready(self) -> None:
        # step 1: fresh instance — ready must be clear until full handshake completes
        app = make_app()
        assert not app.ready.is_set()

        # step 2: ibapi fires nextValidId — safe to send requests now
        app.nextValidId(1)
        assert app.ready.is_set()

    def test_neg_connectack_alone_does_not_set_ready(self) -> None:
        # TCP connected but handshake not yet complete — ready must stay clear
        app = make_app()
        app.connectAck()
        assert app.connected.is_set()   # TCP gate open
        assert not app.ready.is_set()   # request gate still closed

    def test_pos_connectionclosed_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        # connectionClosed fires when TWS drops the connection from its side
        app = make_app()
        with caplog.at_level(logging.WARNING):
            app.connectionClosed()
        assert caplog.messages == ["TWS closed the connection"]


# ── TestMarketDataTypeCallback ────────────────────────────────────────────────


class TestMarketDataTypeCallback:
    """Guard conditions for marketDataType()."""

    def test_pos_known_mode_prints_human_readable_name(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance — market_data_type starts at 0 (not yet confirmed by TWS)
        app = make_app()
        assert app.market_data_type == 0

        # step 2: ibapi confirms mode 1 (live data)
        app.marketDataType(0, 1)

        # step 3: mode is stored and human-readable label appears in output
        assert app.market_data_type == 1
        out = capsys.readouterr().out
        assert "Market data mode:" in out
        assert "live" in out

    def test_neg_unknown_mode_prints_raw_code(self, capsys) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()
        assert app.market_data_type == 0

        # step 2: ibapi sends an unrecognised mode code
        app.marketDataType(0, 99)

        # step 3: mode is stored and raw numeric code used as fallback — no KeyError raised
        assert app.market_data_type == 99
        out = capsys.readouterr().out
        assert "Market data mode:" in out
        assert "99" in out


# ── TestTickPrice ─────────────────────────────────────────────────────────────


class TestTickPrice:
    """Guard conditions and routing logic for tickPrice()."""

    # ── underlying price ──────────────────────────────────────────────────────

    def test_pos_last_price_sets_und_price_and_ready(self) -> None:
        # step 1: fresh instance — und_price absent, event clear
        app = make_app()
        assert app.und_price is None
        assert not app.und_ready.is_set()

        # step 2: tick_type 4 (last traded) arrives
        app.tickPrice(REQ_UNDERLYING, 4, 200.0, MagicMock())

        # step 3: both state fields updated
        assert app.und_price == 200.0
        assert app.und_ready.is_set()

    def test_pos_close_price_fallback_when_no_prior(self) -> None:
        # step 1: no price set yet
        app = make_app()
        assert app.und_price is None

        # step 2: tick_type 9 (close) arrives — accepted as fallback
        app.tickPrice(REQ_UNDERLYING, 9, 198.0, MagicMock())

        # step 3: close price accepted and event set
        assert app.und_price == 198.0
        assert app.und_ready.is_set()

    def test_neg_close_price_ignored_if_last_already_set(self) -> None:
        # step 1: last-traded price already stored
        app = make_app()
        app.tickPrice(REQ_UNDERLYING, 4, 200.0, MagicMock())

        # step 2: close price arrives after last-traded
        app.tickPrice(REQ_UNDERLYING, 9, 150.0, MagicMock())

        # step 3: original value preserved — close does not overwrite last
        assert app.und_price == 200.0

    def test_neg_zero_price_leaves_state_unchanged(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: ibapi sends 0 — signals data unavailable
        app.tickPrice(REQ_UNDERLYING, 4, 0.0, MagicMock())

        # step 3: state untouched — main thread must not be unblocked
        assert app.und_price is None
        assert not app.und_ready.is_set()

    def test_neg_negative_price_leaves_state_unchanged(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: negative price — defensive guard
        app.tickPrice(REQ_UNDERLYING, 4, -5.0, MagicMock())

        # step 3: state untouched
        assert app.und_price is None
        assert not app.und_ready.is_set()

    def test_neg_bid_tick_does_not_set_underlying_price(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: tick_type 1 (bid) for underlying — only 4 and 9 are valid sources
        app.tickPrice(REQ_UNDERLYING, 1, 200.0, MagicMock())

        # step 3: bid tick ignored for underlying — und_price stays None
        assert app.und_price is None
        assert not app.und_ready.is_set()

    # ── call / put routing ────────────────────────────────────────────────────

    def test_pos_call_bid_ask_last_stored(self) -> None:
        # step 1: fresh instance — call_data empty
        app = make_app()
        assert app.call_data == {}

        # step 2: bid, ask, last ticks arrive for the call
        app.tickPrice(REQ_CALL, 1, 1.50, MagicMock())
        app.tickPrice(REQ_CALL, 2, 1.60, MagicMock())
        app.tickPrice(REQ_CALL, 4, 1.55, MagicMock())

        # step 3: all three price fields stored
        assert app.call_data["bid"] == 1.50
        assert app.call_data["ask"] == 1.60
        assert app.call_data["last"] == 1.55

    def test_pos_put_bid_ask_last_stored(self) -> None:
        # step 1: fresh instance — put_data empty
        app = make_app()
        assert app.put_data == {}

        # step 2: bid, ask, last ticks arrive for the put
        app.tickPrice(REQ_PUT, 1, 1.40, MagicMock())
        app.tickPrice(REQ_PUT, 2, 1.50, MagicMock())
        app.tickPrice(REQ_PUT, 4, 1.45, MagicMock())

        # step 3: all three price fields stored
        assert app.put_data["bid"] == 1.40
        assert app.put_data["ask"] == 1.50
        assert app.put_data["last"] == 1.45

    def test_neg_unknown_req_id_writes_nothing(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: tick for an unregistered req_id
        app.tickPrice(99, 4, 200.0, MagicMock())

        # step 3: neither call nor put data touched
        assert app.call_data == {}
        assert app.put_data == {}

    def test_neg_call_tick_does_not_contaminate_put(self) -> None:
        # step 1: fresh instance — put_data empty
        app = make_app()

        # step 2: call price tick arrives
        app.tickPrice(REQ_CALL, 1, 1.50, MagicMock())

        # step 3: put_data remains untouched
        assert app.put_data == {}

    def test_neg_put_tick_does_not_contaminate_call(self) -> None:
        # step 1: fresh instance — call_data empty
        app = make_app()

        # step 2: put price tick arrives
        app.tickPrice(REQ_PUT, 1, 1.40, MagicMock())

        # step 3: call_data remains untouched
        assert app.call_data == {}

    def test_neg_unhandled_tick_type_for_call_writes_nothing(self) -> None:
        # step 1: fresh instance — call_data empty
        app = make_app()

        # step 2: tick_type 9 for call — not 1, 2, or 4, silently ignored
        app.tickPrice(REQ_CALL, 9, 1.50, MagicMock())

        # step 3: call_data stays empty
        assert app.call_data == {}

    def test_neg_unhandled_tick_type_for_put_writes_nothing(self) -> None:
        # step 1: fresh instance — put_data empty
        app = make_app()

        # step 2: tick_type 9 for put — not 1, 2, or 4, silently ignored
        app.tickPrice(REQ_PUT, 9, 1.40, MagicMock())

        # step 3: put_data stays empty
        assert app.put_data == {}

    def test_neg_call_bid_minus_one_stored_as_none(self) -> None:
        # ibapi sends -1.0 for bid/ask when market is closed
        # key must be present with None — distinct from key absent (--- vs N/A in print_data)
        app = make_app()
        app.tickPrice(REQ_CALL, 1, -1.0, MagicMock())
        assert app.call_data == {"bid": None}

    def test_neg_call_ask_minus_one_stored_as_none(self) -> None:
        # same market-closed guard for ask
        app = make_app()
        app.tickPrice(REQ_CALL, 2, -1.0, MagicMock())
        assert app.call_data == {"ask": None}


# ── TestContractDetailsCallbacks ──────────────────────────────────────────────


class TestContractDetailsCallbacks:
    """Guard conditions for contractDetails() and contractDetailsEnd()."""

    def test_neg_wrong_req_id_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()
        assert app.underlying_con_id is None

        # step 2: contractDetails fires for a different request
        app.contractDetails(99, make_contract_details(12345))

        # step 3: conId not stored — wrong request ID
        assert app.underlying_con_id is None

    def test_neg_none_payload_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: ibapi sends None details
        app.contractDetails(REQ_CONTRACT_DETAILS, None)

        # step 3: conId stays None — None payload rejected
        assert app.underlying_con_id is None

    def test_neg_none_inner_contract_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: details object exists but .contract is None
        details = MagicMock()
        details.contract = None
        app.contractDetails(REQ_CONTRACT_DETAILS, details)

        # step 3: conId stays None — .contract is None rejected
        assert app.underlying_con_id is None

    def test_neg_zero_con_id_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: ibapi returns conId=0 — ambiguous contract
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(0))

        # step 3: conId stays None — conId=0 rejected
        assert app.underlying_con_id is None

    def test_pos_contractdetailsend_sets_event(self) -> None:
        # step 1: fresh instance — event clear
        app = make_app()
        assert not app.contract_id_ready.is_set()

        # step 2: End fires for the correct request
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)

        # step 3: event set
        assert app.contract_id_ready.is_set()

    def test_neg_contractdetailsend_wrong_req_id_ignored(self) -> None:
        # step 1: fresh instance — event clear
        app = make_app()

        # step 2: End fires for a different request
        app.contractDetailsEnd(99)

        # step 3: event stays clear
        assert not app.contract_id_ready.is_set()

    def test_pos_first_valid_con_id_stored(self) -> None:
        # step 1: fresh instance — conId absent
        app = make_app()
        assert app.underlying_con_id is None

        # step 2: valid contractDetails arrives for the correct request
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))

        # step 3: conId stored — line 300 exercised
        assert app.underlying_con_id == 12345

    def test_neg_late_callback_after_end_ignored(self) -> None:
        # step 1: End fires first — _contract_details_done flag set
        app = make_app()
        app.contractDetailsEnd(REQ_CONTRACT_DETAILS)
        assert app.underlying_con_id is None

        # step 2: late contractDetails arrives after End
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))

        # step 3: late callback discarded — line 285 guard return exercised
        assert app.underlying_con_id is None

    def test_neg_duplicate_call_before_end_ignored(self) -> None:
        # step 1: first valid conId already stored
        app = make_app()
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(12345))
        assert app.underlying_con_id == 12345

        # step 2: second contractDetails arrives before End
        app.contractDetails(REQ_CONTRACT_DETAILS, make_contract_details(99999))

        # step 3: first conId preserved — line 287 guard return exercised
        assert app.underlying_con_id == 12345


# ── TestOptionParamsCallbacks ─────────────────────────────────────────────────


class TestOptionParamsCallbacks:
    """Guard conditions for securityDefinitionOptionParameter() and End()."""

    def test_pos_smart_expirations_and_strikes_stored(self) -> None:
        # step 1: fresh instance — available sets empty
        app = make_app()
        assert app.available_expirations == set()
        assert app.available_strikes == set()

        # step 2: SMART data arrives
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "SMART", 0, "", "", {"20991231"}, {200.0}
        )

        # step 3: data accumulated in available sets
        assert "20991231" in app.available_expirations
        assert 200.0 in app.available_strikes

    def test_neg_non_smart_exchange_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: CBOE data arrives — only SMART is accepted
        app.securityDefinitionOptionParameter(
            REQ_OPT_PARAMS, "CBOE", 0, "", "", {"20991231"}, {200.0}
        )

        # step 3: available sets remain empty
        assert app.available_expirations == set()
        assert app.available_strikes == set()

    def test_neg_wrong_req_id_ignored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: SMART data arrives for a different request
        app.securityDefinitionOptionParameter(
            99, "SMART", 0, "", "", {"20991231"}, {200.0}
        )

        # step 3: available sets remain empty — wrong req_id
        assert app.available_expirations == set()
        assert app.available_strikes == set()

    def test_pos_end_sets_params_ready(self) -> None:
        # step 1: fresh instance — event clear
        app = make_app()
        assert not app.params_ready.is_set()

        # step 2: End fires for the correct request
        app.securityDefinitionOptionParameterEnd(REQ_OPT_PARAMS)

        # step 3: event set
        assert app.params_ready.is_set()

    def test_neg_end_wrong_req_id_ignored(self) -> None:
        # step 1: fresh instance — event clear
        app = make_app()

        # step 2: End fires for a different request
        app.securityDefinitionOptionParameterEnd(99)

        # step 3: event stays clear
        assert not app.params_ready.is_set()


# ── TestGreeksCallbacks ───────────────────────────────────────────────────────


class TestGreeksCallbacks:
    """Guard conditions for tickOptionComputation()."""

    _GREEK_DEFAULTS: ClassVar[dict[str, object]] = dict(
        tick_type=13, _tick_attrib=0,
        implied_vol=0.25, delta=0.45, _opt_price=1.5, _pv_dividend=0.0,
        gamma=0.02, vega=0.15, theta=-0.05, _und_price=200.0,
    )

    def _fire(self, app: TestConnection, req_id: int, **overrides: object) -> None:
        app.tickOptionComputation(req_id, **{**self._GREEK_DEFAULTS, **overrides})  # type: ignore[arg-type]

    def test_pos_call_greeks_stored_on_tick_type_13(self) -> None:
        # step 1: fresh instance — call_data empty
        app = make_app()
        assert app.call_data == {}

        # step 2: model-price Greeks tick arrives (tick_type 13)
        self._fire(app, REQ_CALL)

        # step 3: all Greek fields stored in call_data
        assert app.call_data["iv"] == 0.25
        assert app.call_data["delta"] == 0.45
        assert app.call_data["gamma"] == 0.02
        assert app.call_data["theta"] == -0.05
        assert app.call_data["vega"] == 0.15

    def test_pos_put_greeks_stored_on_tick_type_13(self) -> None:
        # step 1: fresh instance — put_data empty
        app = make_app()
        assert app.put_data == {}

        # step 2: model-price Greeks tick arrives for the put
        self._fire(app, REQ_PUT, delta=-0.55)

        # step 3: Greek fields stored in put_data
        assert app.put_data["delta"] == -0.55
        assert app.put_data["iv"] == 0.25

    def test_neg_non_model_tick_type_not_stored(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: tick_type 10 (not model price) arrives
        self._fire(app, REQ_CALL, tick_type=10)

        # step 3: call_data remains empty — only tick_type 13 is accepted
        assert app.call_data == {}

    def test_neg_unknown_req_id_writes_nothing(self) -> None:
        # step 1: fresh instance
        app = make_app()

        # step 2: Greeks tick for an unregistered req_id
        self._fire(app, 99)

        # step 3: neither call nor put data touched
        assert app.call_data == {}
        assert app.put_data == {}

    def test_neg_call_greeks_do_not_contaminate_put(self) -> None:
        # step 1: fresh instance — put_data empty
        app = make_app()

        # step 2: call Greeks arrive
        self._fire(app, REQ_CALL)

        # step 3: put_data stays empty
        assert app.put_data == {}

    def test_neg_put_greeks_do_not_contaminate_call(self) -> None:
        # step 1: fresh instance — call_data empty
        app = make_app()

        # step 2: put Greeks arrive
        self._fire(app, REQ_PUT)

        # step 3: call_data stays empty
        assert app.call_data == {}

    def test_neg_nan_delta_stored_as_none(self) -> None:
        # NaN is one of three ways ibapi signals a Greek is unavailable
        app = make_app()
        self._fire(app, REQ_CALL, delta=float("nan"))
        assert app.call_data["delta"] is None

    def test_neg_sentinel_iv_stored_as_none(self) -> None:
        # abs(x) > 1e6 is ibapi's sentinel for an uncomputable Greek
        app = make_app()
        self._fire(app, REQ_CALL, implied_vol=2e6)
        assert app.call_data["iv"] is None


# ── TestErrorCallback ─────────────────────────────────────────────────────────


class TestErrorCallback:
    """Guard conditions for error()."""

    def test_neg_info_code_produces_no_output(self, capsys, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: ibapi fires a 2xxx status notification (not a real error)
        with caplog.at_level(logging.INFO):
            app.error(1, "", 2104, "Data farm connected", "")

        # step 3: no stdout output AND exactly one INFO record — not an error
        assert capsys.readouterr().out == ""
        assert caplog.messages == ["TWS: Data farm connected"]

    def test_neg_info_range_boundaries_silent(self, capsys, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: fire codes at both ends of the INFO_CODES range
        with caplog.at_level(logging.INFO):
            app.error(-1, "", 2000, "range start", "")
            app.error(-1, "", 2999, "range end", "")

        # step 3: no stdout output AND exactly two INFO records — not errors
        assert capsys.readouterr().out == ""
        assert caplog.messages == ["TWS: range start", "TWS: range end"]

    def test_neg_code_below_info_range_is_printed(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: error code 1999 — just below INFO_CODES range
        app.error(-1, "", 1999, "below range", "")

        # step 3: exactly one log record with the full formatted message
        assert caplog.messages == ["IBKR 1999 (req -1): below range"]

    def test_neg_code_above_info_range_is_printed(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: error code 3000 — just above INFO_CODES range
        app.error(-1, "", 3000, "above range", "")

        # step 3: exactly one log record with the full formatted message
        assert caplog.messages == ["IBKR 3000 (req -1): above range"]

    def test_pos_known_error_shows_custom_description(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: fire a known error code (502 = cannot connect to TWS)
        app.error(-1, "", 502, "original ibapi message", "")

        # step 3: custom description used — exact equality also excludes the raw ibapi message
        assert caplog.messages == [f"IBKR 502 (req -1): {KNOWN_ERRORS[502]}"]

    def test_pos_unknown_error_shows_raw_message(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: fire an error code not in KNOWN_ERRORS
        app.error(-1, "", 9999, "raw ibapi error text", "")

        # step 3: raw message used as fallback
        assert caplog.messages == ["IBKR 9999 (req -1): raw ibapi error text"]

    def test_pos_error_output_contains_code_and_req_id(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # step 1: fresh instance
        app = make_app()

        # step 2: fire an error tied to a specific request
        app.error(42, "", 9999, "something failed", "")

        # step 3: full formatted message with code and request ID
        assert caplog.messages == ["IBKR 9999 (req 42): something failed"]

    def test_neg_malformed_args_are_silently_discarded(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # args don't match either ibapi version pattern — exercises the else: return branch
        app = make_app()
        with caplog.at_level(logging.DEBUG):
            app.error("not-an-int", "not-an-int")   # too few args, no int in positions 1 or 2
        assert caplog.messages == []

    def test_pos_pre_10_30_signature_parsed_and_logged(self, caplog) -> None:  # type: ignore[no-untyped-def]
        # pre-10.30 ibapi omits errorTime — signature is (reqId:int, errorCode:int, errorString:str)
        app = make_app()
        app.error(5, 9999, "pre-10.30 error message")
        assert caplog.messages == ["IBKR 9999 (req 5): pre-10.30 error message"]
