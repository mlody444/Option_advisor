"""Automated CI qualification tests for main() (SWE.6, Set 1).

TestConnection is replaced by a MagicMock whose Event gates return True/False
instantly — no real timeouts, no TWS connection needed.
For positive-path tests, time.sleep is patched to raise KeyboardInterrupt so
the streaming loop exits after one print_data call.
Assertions are on stdout (capsys) and app.disconnect.call_count.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from drafts.test_connection import SYMBOL, TARGET_DTE, main


# ── helpers ───────────────────────────────────────────────────────────────────


def _future_expiry(days: int) -> str:
    """Return an IBKR-format expiry string that is ``days`` days from today.

    Args:
        days (int): Number of days from today.

    Returns:
        str: Date string in YYYYMMDD format.
    """
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")


def _make_mock_app(
    *,
    connected: bool = True,
    ready: bool = True,
    und_ready: bool = True,
    contract_id_ready: bool = True,
    params_ready: bool = True,
    und_price: float = 200.0,
    underlying_con_id: int | None = 12345,
    available_expirations: set[str] | None = None,
    available_strikes: set[float] | None = None,
    ibapi_crashed: bool = False,
    failure_message: str | None = None,
) -> MagicMock:
    """Return a MagicMock TestConnection with configurable flow outcomes.

    All Event gate wait() calls return the supplied booleans instantly.
    Defaults produce a fully healthy app that reaches the streaming loop.

    Args:
        connected (bool): Return value for connected.wait().
        ready (bool): Return value for ready.wait().
        und_ready (bool): Return value for und_ready.wait().
        contract_id_ready (bool): Return value for contract_id_ready.wait().
        params_ready (bool): Return value for params_ready.wait().
        und_price (float): Simulated underlying price.
        underlying_con_id (int | None): Simulated IBKR contract ID.
        available_expirations (set[str] | None): Option chain expiry dates.
            Defaults to a single expiry at TARGET_DTE days from today.
        available_strikes (set[float] | None): Option chain strikes.
            Defaults to a single strike at und_price.
        ibapi_crashed (bool): Whether failed.is_set() returns True.
        failure_message (str | None): Value stored in app.failure_message.

    Returns:
        MagicMock: Configured mock TestConnection instance.
    """
    if available_expirations is None:
        available_expirations = {_future_expiry(TARGET_DTE)}
    if available_strikes is None:
        available_strikes = {und_price}
    app = MagicMock()
    app.connected.wait.return_value = connected
    app.ready.wait.return_value = ready
    app.und_ready.wait.return_value = und_ready
    app.contract_id_ready.wait.return_value = contract_id_ready
    app.params_ready.wait.return_value = params_ready
    app.und_price = und_price
    app.underlying_con_id = underlying_con_id
    app.available_expirations = available_expirations
    app.available_strikes = available_strikes
    app.call_data = {}
    app.put_data = {}
    app.failed.is_set.return_value = ibapi_crashed
    app.failure_message = failure_message
    return app


# ── TestConnectionPhase ───────────────────────────────────────────────────────


class TestConnectionPhase:
    """main() two-stage handshake: connectAck (TCP) then nextValidId (full).

    Positive path: both events fire — "Connected" and "Handshake complete" printed.
    Negative paths: timeout at each gate prints the specific error and disconnects.
    Crash path: ibapi thread crash overrides the generic timeout message with
    the stored failure_message.
    """

    def test_pos_connection_established_prints_messages(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # und_ready=False gives a clean early exit after the connection messages
        app = _make_mock_app(und_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "Connected to TWS"
        assert lines[1] == "Handshake complete — sending requests"
        assert app.disconnect.call_count == 1

    def test_neg_connect_timeout_prints_error_and_disconnects(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(connected=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        out = capsys.readouterr().out
        assert out == "Could not connect to TWS — check host, port and API settings\n"
        assert app.disconnect.call_count == 1

    def test_neg_ready_timeout_prints_error_and_disconnects(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        out = capsys.readouterr().out
        assert out == "Connected to TWS\nHandshake incomplete — nextValidId never fired\n"
        assert app.disconnect.call_count == 1

    def test_neg_ibapi_crash_shows_failure_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # crash path: failure_message is printed instead of the generic timeout text
        app = _make_mock_app(connected=False, ibapi_crashed=True, failure_message="test crash reason")
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        assert capsys.readouterr().out == "test crash reason\n"


# ── TestUnderlyingPricePhase ──────────────────────────────────────────────────


class TestUnderlyingPricePhase:
    """main() underlying price gate: reqMktData → tickPrice → und_ready.

    Positive path: price is printed to stdout.
    Negative path: timeout prints the specific error and calls disconnect().
    """

    def test_pos_price_received_prints_symbol_and_value(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # contract_id_ready=False gives a clean early exit after the price line
        app = _make_mock_app(contract_id_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[2] == f"{SYMBOL} price: {app.und_price}"
        assert app.disconnect.call_count == 1

    def test_neg_price_timeout_prints_error_and_disconnects(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(und_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[2] == "Could not get underlying price — check TWS connection"
        assert app.disconnect.call_count == 1


# ── TestContractIdPhase ───────────────────────────────────────────────────────


class TestContractIdPhase:
    """main() contract ID gate: reqContractDetails → contractDetailsEnd.

    Positive path: conId is printed.
    Negative paths: timeout; event fires but conId is None (ambiguous contract).
    """

    def test_pos_contract_id_found_prints_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # params_ready=False gives a clean early exit after the contract ID line
        app = _make_mock_app(params_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[3] == f"{SYMBOL} contract ID: {app.underlying_con_id}"
        assert app.disconnect.call_count == 1

    def test_neg_contract_id_timeout_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(contract_id_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[3] == f"Could not get {SYMBOL} contract ID — check TWS connection"
        assert app.disconnect.call_count == 1

    def test_neg_no_valid_con_id_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(underlying_con_id=None)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[3] == f"Contract details returned no valid conId for {SYMBOL}"
        assert app.disconnect.call_count == 1


# ── TestOptionChainPhase ──────────────────────────────────────────────────────


class TestOptionChainPhase:
    """main() option chain gate: reqSecDefOptParams → params_ready → selection.

    Positive path: "Using expiry ... strike ..." printed.
    Negative paths: timeout; empty expirations; empty strikes.
    """

    def test_pos_expiry_and_strike_selected_prints_using(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        expiry = _future_expiry(TARGET_DTE)
        app = _make_mock_app(available_expirations={expiry}, available_strikes={200.0})
        with patch("drafts.test_connection.TestConnection", return_value=app):
            with patch("drafts.test_connection.time.sleep", side_effect=KeyboardInterrupt):
                main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[4] == f"Using expiry {expiry} (DTE {TARGET_DTE})  strike 200.0"
        assert app.disconnect.call_count == 1

    def test_neg_params_timeout_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(params_ready=False)
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[4] == "Could not get option parameters — check TWS connection"
        assert app.disconnect.call_count == 1

    def test_neg_no_valid_expiry_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app(available_expirations=set())
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[4] == "No valid expiry found — received 0 expirations, all may be expired"
        assert app.disconnect.call_count == 1

    def test_neg_no_valid_strike_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        expiry = _future_expiry(TARGET_DTE)
        app = _make_mock_app(available_expirations={expiry}, available_strikes=set())
        with patch("drafts.test_connection.TestConnection", return_value=app):
            main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[4] == f"No strike found — received 0 strikes for underlying price {app.und_price}"
        assert app.disconnect.call_count == 1


# ── TestStreamingPhase ────────────────────────────────────────────────────────


class TestStreamingPhase:
    """main() streaming loop and cleanup.

    Positive paths: streaming message printed before Ctrl+C; disconnect()
    called in finally regardless of how the loop exits.
    """

    def test_pos_streaming_message_printed_then_ctrl_c_handled(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _make_mock_app()
        with patch("drafts.test_connection.TestConnection", return_value=app):
            with patch("drafts.test_connection.time.sleep", side_effect=KeyboardInterrupt):
                main()
        lines = capsys.readouterr().out.splitlines()
        assert lines[6] == "Streaming data — press Ctrl+C to stop"
        assert lines[-1] == "Stopped by user"

    def test_pos_disconnect_always_called_even_on_ctrl_c(self) -> None:
        app = _make_mock_app()
        with patch("drafts.test_connection.TestConnection", return_value=app):
            with patch("drafts.test_connection.time.sleep", side_effect=KeyboardInterrupt):
                main()
        assert app.disconnect.call_count == 1
