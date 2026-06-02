"""Manual live qualification tests for TestConnection (SWE.6, Set 2).

All tests are marked @pytest.mark.live and require TWS running on
127.0.0.1:5931 with API enabled. Excluded from CI runs.

Run locally:
    pytest tests/qualification/test_live_flow.py -v -m live

Each test is independent: it creates its own connection via the live_app
fixture, drives the flow to the step under test, asserts on state, and
disconnects automatically when the fixture tears down.
"""

import threading
import time
from collections.abc import Generator

import pytest

from drafts.ibkr_utils import find_closest_expiry, find_closest_strike
from drafts.test_connection import (
    CLIENT_ID,
    CONNECT_TIMEOUT,
    DATA_TIMEOUT,
    HOST,
    PORT,
    REQ_CALL,
    REQ_CONTRACT_DETAILS,
    REQ_OPT_PARAMS,
    REQ_PUT,
    REQ_UNDERLYING,
    SYMBOL,
    TARGET_DTE,
    TestConnection,
)
from ibapi.contract import Contract  # type: ignore[import-untyped]

GREEK_WAIT = 30   # seconds to poll for Greeks after subscribing to options
GREEK_POLL = 0.5  # polling interval in seconds


# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def live_app() -> Generator[TestConnection, None, None]:
    """Create a connected TestConnection and tear it down after the test.

    Yields:
        TestConnection: App instance with the ibapi message loop running
            in a daemon thread. Disconnects automatically after the test.
    """
    app = TestConnection()
    app.connect(HOST, PORT, CLIENT_ID)
    thread = threading.Thread(target=app.run, daemon=True, name="ibapi-live-test")
    thread.start()
    yield app
    app.disconnect()


# ── helpers ───────────────────────────────────────────────────────────────────


def _handshake(app: TestConnection) -> None:
    """Assert connectAck and nextValidId arrive; set frozen market data mode.

    Args:
        app (TestConnection): Connected TestConnection instance.
    """
    assert app.connected.wait(timeout=CONNECT_TIMEOUT), "connectAck timed out"
    assert app.ready.wait(timeout=CONNECT_TIMEOUT), "nextValidId timed out"
    app.reqMarketDataType(2)


def _request_underlying_price(app: TestConnection) -> Contract:
    """Request the IWM underlying price and return the contract for reuse.

    Args:
        app (TestConnection): Connected and handshaked TestConnection.

    Returns:
        Contract: IWM stock contract used for subsequent requests.
    """
    und_contract = Contract()
    und_contract.symbol = SYMBOL
    und_contract.secType = "STK"
    und_contract.exchange = "SMART"
    und_contract.currency = "USD"
    app.reqMktData(
        reqId=REQ_UNDERLYING,
        contract=und_contract,
        genericTickList="",
        snapshot=False,
        regulatorySnapshot=False,
        mktDataOptions=[],
    )
    assert app.und_ready.wait(timeout=DATA_TIMEOUT), "underlying price timed out"
    return und_contract


def _request_contract_id(app: TestConnection, und_contract: Contract) -> None:
    """Request and wait for the IWM internal IBKR contract ID.

    Args:
        app (TestConnection): TestConnection with a valid underlying price.
        und_contract (Contract): IWM stock contract to look up.
    """
    app.reqContractDetails(reqId=REQ_CONTRACT_DETAILS, contract=und_contract)
    assert app.contract_id_ready.wait(timeout=DATA_TIMEOUT), "contract ID timed out"
    assert app.underlying_con_id is not None, "no valid conId returned by TWS"


def _request_option_params(app: TestConnection) -> None:
    """Request and wait for available IWM option expirations and strikes.

    Args:
        app (TestConnection): TestConnection with a resolved underlying_con_id.
    """
    assert app.underlying_con_id is not None  # nosec B101 — narrows type for reqSecDefOptParams
    app.reqSecDefOptParams(
        reqId=REQ_OPT_PARAMS,
        underlyingSymbol=SYMBOL,
        futFopExchange="",
        underlyingSecType="STK",
        underlyingConId=app.underlying_con_id,
    )
    assert app.params_ready.wait(timeout=DATA_TIMEOUT), "option params timed out"


# ── TestLiveTWSConnection ─────────────────────────────────────────────────────


class TestLiveTWSConnection:
    """End-to-end qualification against a real TWS session (SWE.6, Set 2).

    Each test creates a fresh connection via live_app, drives it through
    the flow up to the step under test, and asserts on the resulting state.
    Requires TWS on 127.0.0.1:5931 with API enabled. Run with: pytest -m live
    """

    @pytest.mark.live
    def test_live_connects_and_handshake_completes(
        self, live_app: TestConnection
    ) -> None:
        assert live_app.connected.wait(timeout=CONNECT_TIMEOUT), "connectAck timed out"
        assert live_app.ready.wait(timeout=CONNECT_TIMEOUT), "nextValidId timed out"

    @pytest.mark.live
    def test_live_underlying_price_received(self, live_app: TestConnection) -> None:
        _handshake(live_app)
        _request_underlying_price(live_app)
        assert live_app.market_data_type in {1, 2, 3, 4}, "unexpected market data mode"
        assert isinstance(live_app.und_price, float)
        assert live_app.und_price > 0

    @pytest.mark.live
    def test_live_contract_id_resolved(self, live_app: TestConnection) -> None:
        _handshake(live_app)
        und_contract = _request_underlying_price(live_app)
        _request_contract_id(live_app, und_contract)
        assert isinstance(live_app.underlying_con_id, int)
        assert live_app.underlying_con_id > 0

    @pytest.mark.live
    def test_live_option_chain_parameters_loaded(
        self, live_app: TestConnection
    ) -> None:
        _handshake(live_app)
        und_contract = _request_underlying_price(live_app)
        _request_contract_id(live_app, und_contract)
        _request_option_params(live_app)
        assert len(live_app.available_expirations) > 0
        assert len(live_app.available_strikes) > 0

    @pytest.mark.live
    def test_live_atm_greeks_populate_within_30s(
        self, live_app: TestConnection
    ) -> None:
        _handshake(live_app)
        und_contract = _request_underlying_price(live_app)
        _request_contract_id(live_app, und_contract)
        _request_option_params(live_app)

        assert live_app.und_price is not None  # nosec B101 — guaranteed by und_ready
        expiry = find_closest_expiry(live_app.available_expirations, TARGET_DTE)
        strike = find_closest_strike(live_app.available_strikes, live_app.und_price)
        assert expiry is not None, "no valid expiry found in option chain"
        assert strike is not None, "no valid strike found in option chain"

        for req_id, right in [(REQ_CALL, "C"), (REQ_PUT, "P")]:
            opt_contract = Contract()
            opt_contract.symbol = SYMBOL
            opt_contract.secType = "OPT"
            opt_contract.exchange = "SMART"
            opt_contract.currency = "USD"
            opt_contract.lastTradeDateOrContractMonth = expiry
            opt_contract.strike = strike
            opt_contract.right = right
            opt_contract.multiplier = "100"
            live_app.reqMktData(
                reqId=req_id,
                contract=opt_contract,
                genericTickList="",
                snapshot=False,
                regulatorySnapshot=False,
                mktDataOptions=[],
            )

        # poll until delta arrives for both legs or the timeout expires
        deadline = time.monotonic() + GREEK_WAIT
        while time.monotonic() < deadline:
            if (
                live_app.call_data.get("delta") is not None
                and live_app.put_data.get("delta") is not None
            ):
                break
            time.sleep(GREEK_POLL)

        if live_app.market_data_type == 1:
            # live market — all key Greeks must arrive within the timeout
            for key in ("iv", "delta", "gamma"):
                assert live_app.call_data.get(key) is not None, f"call {key} missing in live mode"
                assert live_app.put_data.get(key) is not None, f"put {key} missing in live mode"
        else:
            # frozen / delayed — delta is the minimum expected from last known values
            assert live_app.call_data.get("delta") is not None, "call delta missing in frozen mode"
            assert live_app.put_data.get("delta") is not None, "put delta missing in frozen mode"
