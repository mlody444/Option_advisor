"""
Quick connection test — does NOT write any files.

What it does:
  1. Connects to TWS
  2. Gets the current IWM price
  3. Finds the expiry closest to 7 DTE
  4. Finds the strike closest to ATM (current price)
  5. Subscribes to that call and put
  6. Prints the latest Greeks + prices every 2 seconds
"""

import logging
import threading
import time
from datetime import date

from ibapi.client import EClient
from ibapi.common import TickAttrib  # type hint for tickPrice _attrib parameter
from ibapi.contract import Contract, ContractDetails  # type hint for contractDetails callback
from ibapi.wrapper import EWrapper

from drafts.ibkr_utils import (
    expiry_to_date,
    find_closest_expiry,
    find_closest_strike,
    print_data,
    valid_greek,
)

logger = logging.getLogger(__name__)

# ── TWS connection settings ───────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 5931
CLIENT_ID = 10  # any number not used by other connections
SYMBOL = "IWM"
TARGET_DTE = 7  # find the expiry closest to this number of days


# ── request ID constants ──────────────────────────────────────────────────────
REQ_UNDERLYING = 1
REQ_OPT_PARAMS = 2
REQ_CALL = 3
REQ_PUT = 4
REQ_CONTRACT_DETAILS = 5


# ── ibapi error handling ──────────────────────────────────────────────────────

# ibapi routes ALL messages — real errors AND status notifications — through the
# single error() callback. The two groups below are completely separate:
#
#   INFO_CODES   — not errors at all; TWS sends these to report data farm status
#                  (connected, reconnecting, etc.). Safe to ignore silently.
#
#   KNOWN_ERRORS — real error codes where ibapi's default message is cryptic.
#                  We replace them with plain-English descriptions.
#                  Any code not listed here falls back to ibapi's own message.
#
# ibapi 10.30+ added error_time as second parameter to error()

KNOWN_ERRORS = {
    502: (
        "Cannot connect to TWS — check that TWS is running and API is enabled "
        "(Edit → Global Configuration → API → Settings)"
    ),
    504: "Not connected — request was sent before connection was established",
    200: "No security definition found — check symbol, exchange, or contract details",
    354: "Requested market data not subscribed — check your IBKR market data subscriptions",
    10090: "Part of requested market data is not subscribed",
}


# ── program flow ──────────────────────────────────────────────────────────────
# 1. connect()             → connectAck fires            → connected.set()
# 2. reqMktData()          → tickPrice fires              → und_ready.set()
# 3. reqContractDetails()  → contractDetailsEnd fires     → contract_id_ready.set()
# 4. reqSecDefOptParams()  → securityDefinitionOptionParameter fires
#                          → params_ready.set()
# 5. find_closest_expiry() + find_closest_strike() — pick the target contract
# 6. reqMktData() call+put → tickPrice / tickOptionComputation fill call_data / put_data
# 7. print_data() every 2 s — Ctrl+C to stop


# ── ibapi callbacks ───────────────────────────────────────────────────────────


class TestConnection(EWrapper, EClient):
    """ibapi wrapper and client combined — connects to TWS and collects option data.

    Inherits EWrapper to receive callbacks
    Inherits EClient to send requests.
    The same object plays both roles; EClient receives self as its wrapper.
    All collected state is stored as plain instance attributes and read by main().

    Attributes:
        INFO_CODES (range): ibapi status codes 2000-2999 — status notifications, not errors.
        und_price (float | None): Last known underlying price, set by tickPrice().
        und_ready (threading.Event): Set when the first valid underlying price arrives.
        available_expirations (set[str]): Expiry strings from reqSecDefOptParams().
        available_strikes (set[float]): Strike prices from reqSecDefOptParams().
        params_ready (threading.Event): Set when option parameters are fully loaded.
        call_data (dict[str, float | None]): Latest ATM call data —
            bid, ask, iv, delta, gamma, theta, vega.
        put_data (dict[str, float | None]): Latest ATM put data — same structure as call_data.
        connected (threading.Event): Set when TWS fires connectAck.
        underlying_con_id (int | None): Internal IBKR contract ID, set by contractDetails().
        contract_id_ready (threading.Event): Set when contractDetailsEnd fires.
    """

    # ibapi's 2000-2999 range = status notifications (data farm connected, etc.)
    # using range() means any new 2xxx code ibapi adds is handled automatically.
    # subclass can override with a different range or a specific tuple if needed.
    INFO_CODES: range = range(2000, 3000)

    und_price: float | None
    und_ready: threading.Event
    available_expirations: set[str]
    available_strikes: set[float]
    params_ready: threading.Event
    call_data: dict[str, float | None]
    put_data: dict[str, float | None]
    connected: threading.Event
    underlying_con_id: int | None
    contract_id_ready: threading.Event
    _contract_details_done: bool

    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)  # pass self as wrapper — same object handles callbacks

        # underlying price
        self.und_price = None
        self.und_ready = threading.Event()

        # available option chain from IBKR
        self.available_expirations = set()
        self.available_strikes = set()
        self.params_ready = threading.Event()

        # latest data for the ATM call and put (filled by callbacks)
        self.call_data = {}
        self.put_data = {}

        # set when TWS confirms the connection is established
        self.connected = threading.Event()

        # underlying's internal IBKR contract ID — needed for reqSecDefOptParams
        self.underlying_con_id = None
        self.contract_id_ready = threading.Event()
        self._contract_details_done = False

    # ── connection (flow step 1) ──────────────────────────────────────────────

    # fired by ibapi once after connect() succeeds — confirms the session is live
    def connectAck(self) -> None:
        """Confirm connection to TWS is established.

        Fired by ibapi once after connect() succeeds. Sets the connected
        event so the main thread can continue past its wait() call.
        """
        self.connected.set()

    def marketDataType(self, _: int, market_data_type: int) -> None:
        """Log the active market data mode after reqMarketDataType() is called.

        Fired by ibapi to confirm the mode switch. Prints a human-readable
        name for the active mode.

        Args:
            market_data_type (int): Active mode code — 1 live, 2 frozen,
                3 delayed 15 min, 4 delayed frozen.
        """
        names = {
            1: "live",
            2: "frozen (last values — used when market is closed)",
            3: "delayed 15 min",
            4: "delayed frozen",
        }
        name = names.get(market_data_type, str(market_data_type))
        print(f"Market data mode: {name}")

    # fired by ibapi for every error AND every status notification — both come through here
    def error(
        self,
        req_id: int,
        _error_time: str,
        error_code: int,
        error_string: str,
        _advanced_order_reject_desc: str = "",
    ) -> None:
        """Handle errors and status notifications from TWS.

        Fired by ibapi for both real errors and info-level status notifications.
        INFO_CODES (2000-2999) are silently ignored. Real errors are printed
        with a plain-English description where available, otherwise the raw
        ibapi message is used.

        Args:
            req_id (int): ID of the request that caused the error, or -1
                for connection-level errors not tied to a specific request.
            _error_time (str): Timestamp of the error — not used by this
                implementation.
            error_code (int): ibapi error code. Codes in INFO_CODES are
                status notifications, not real errors.
            error_string (str): ibapi's default message. Used as fallback
                when error_code is not in KNOWN_ERRORS.
            _advanced_order_reject_desc (str): Order reject detail for
                order errors — not used by this implementation.
        """
        # silently ignore status notifications — they are not errors
        if error_code in self.INFO_CODES:
            return
        # use our plain-English description if available, otherwise ibapi's own message
        description = KNOWN_ERRORS.get(error_code, error_string)
        print(f"IBKR error {error_code} (req {req_id}): {description}")

    # ── underlying price (flow step 2) ───────────────────────────────────────

    # fired by ibapi for every price tick from reqMktData() — underlying, call, and put
    def tickPrice(self, req_id: int, tick_type: int, price: float, _attrib: TickAttrib) -> None:
        """Store incoming price ticks for the underlying, call, and put.

        Fired by ibapi for every price update from reqMktData(). Routes
        each tick to the correct data store based on req_id. Prices <= 0
        are ignored — ibapi sends 0 when data is unavailable.

        Args:
            req_id (int): Identifies the subscription — REQ_UNDERLYING,
                REQ_CALL, or REQ_PUT.
            tick_type (int): Price category — 1 bid, 2 ask, 4 last traded,
                9 close (used as underlying fallback when market is closed).
            price (float): Tick value in USD. Ignored if <= 0.
            _attrib (TickAttrib): Additional tick attributes — not used by
                this implementation.
        """
        if price <= 0:
            return

        if req_id == REQ_UNDERLYING:
            logger.debug(f"tick — type: {tick_type}  price: {price}")
            # tick type 4 = last traded price
            # tick type 9 = close price — only used as fallback when market is closed
            if tick_type == 4 or (tick_type == 9 and self.und_price is None):
                self.und_price = price
                self.und_ready.set()

        elif req_id == REQ_CALL:
            if tick_type == 1:
                self.call_data["bid"] = price
            elif tick_type == 2:
                self.call_data["ask"] = price
            elif tick_type == 4:
                self.call_data["last"] = price

        elif req_id == REQ_PUT:
            if tick_type == 1:
                self.put_data["bid"] = price
            elif tick_type == 2:
                self.put_data["ask"] = price
            elif tick_type == 4:
                self.put_data["last"] = price

    # ── contract ID (flow step 3) ─────────────────────────────────────────────

    # fired by ibapi for each result returned by reqContractDetails()
    # one call per matching contract — IBKR may return several for ambiguous symbols
    def contractDetails(self, req_id: int, contract_details: ContractDetails | None) -> None:
        """Store the first valid IBKR contract ID returned by reqContractDetails().

        Fired once per matching contract. Only the first result with a non-zero
        conId is stored; subsequent results are ignored. Any call arriving after
        contractDetailsEnd() has fired is also silently ignored.

        Args:
            req_id (int): Identifies the request — only REQ_CONTRACT_DETAILS
                is handled.
            contract_details (ContractDetails | None): Contract data returned
                by TWS. May be None or contain conId=0 for ambiguous contracts.
        """
        if req_id != REQ_CONTRACT_DETAILS:
            return
        if self._contract_details_done:
            return  # End already fired — discard any late callbacks
        if self.underlying_con_id is not None:
            return  # already stored the first valid result — ignore subsequent ones
        if contract_details is None:
            print("contractDetails: received None — skipping")
            return
        # .contract is always set by ibapi, but guard the chain before accessing .conId
        if contract_details.contract is None:
            print("contractDetails: received details with no contract — skipping")
            return
        con_id = contract_details.contract.conId
        if con_id == 0:
            print("contractDetails: received conId=0 — contract may be ambiguous, skipping")
            return
        # save the internal IBKR contract ID from the first result
        self.underlying_con_id = con_id

    # fired by ibapi once after all contractDetails() results have been delivered
    def contractDetailsEnd(self, req_id: int) -> None:
        """Signal that all contractDetails() results have been delivered.

        Fired by ibapi once after the last contractDetails() call for a given
        request. Sets contract_id_ready so the main thread can continue.

        Args:
            req_id (int): Identifies the completed request — only
                REQ_CONTRACT_DETAILS is handled.
        """
        if req_id == REQ_CONTRACT_DETAILS:
            self._contract_details_done = True
            self.contract_id_ready.set()

    # ── option params (flow step 4) ───────────────────────────────────────────

    # fired by ibapi once per exchange in response to reqSecDefOptParams()
    # delivers all available expirations and strikes for that exchange
    def securityDefinitionOptionParameter(
        self,
        req_id: int,
        exchange: str,
        _underlying_con_id: int,
        _trading_class: str,
        _multiplier: str,
        expirations: set[str],
        strikes: set[float],
    ) -> None:
        """Accumulate available expirations and strikes from one exchange.

        Fired by ibapi once per exchange in response to reqSecDefOptParams().
        Only SMART exchange data is kept to avoid duplicates across venues.

        Args:
            req_id (int): Identifies the request — only REQ_OPT_PARAMS
                is handled.
            exchange (str): Exchange name, e.g. "SMART", "CBOE", "AMEX".
                Only "SMART" data is stored.
            _underlying_con_id (int): Underlying contract ID echoed back
                by ibapi — not used by this implementation.
            _trading_class (str): Option trading class — not used by this
                implementation.
            _multiplier (str): Contract multiplier — not used by this
                implementation.
            expirations (set[str]): Available expiry dates in YYYYMMDD format.
            strikes (set[float]): Available strike prices in USD.
        """
        if req_id != REQ_OPT_PARAMS:
            return
        logger.debug(
            f"params — exchange: {exchange}  "
            f"expirations: {len(expirations)}  strikes: {len(strikes)}"
        )
        # we only keep SMART exchange data to avoid duplicates
        if exchange == "SMART":
            self.available_expirations.update(expirations)
            self.available_strikes.update(strikes)

    # fired by ibapi once after all securityDefinitionOptionParameter() calls are done
    # only now is it safe to read available_expirations and available_strikes
    def securityDefinitionOptionParameterEnd(self, req_id: int) -> None:
        """Signal that all securityDefinitionOptionParameter() calls are done.

        Fired by ibapi once after the last exchange result has been delivered.
        Only after it is safe to read available_expirations and
        available_strikes. Sets params_ready so the main thread can continue.

        Args:
            req_id (int): Identifies the completed request — only
                REQ_OPT_PARAMS is handled.
        """
        if req_id != REQ_OPT_PARAMS:
            return
        logger.debug(
            f"params end — total expirations: {len(self.available_expirations)}  "
            f"total strikes: {len(self.available_strikes)}"
        )
        self.params_ready.set()

    # ── option Greeks (flow step 6) ───────────────────────────────────────────

    # fired by ibapi for every Greeks tick from reqMktData() on an option contract
    def tickOptionComputation(
        self,
        req_id: int,
        tick_type: int,
        _tick_attrib: int,
        implied_vol: float,
        delta: float,
        _opt_price: float,
        _pv_dividend: float,
        gamma: float,
        vega: float,
        theta: float,
        _und_price: float,
    ) -> None:
        """Store incoming Greeks for the ATM call and put.

        Fired by ibapi for every Greeks tick from reqMktData() on an option.
        Only tick_type 13 (model price) is stored — it is the most reliable
        source. Each value is validated through valid_greek() before storing.

        Args:
            req_id (int): Identifies the subscription — REQ_CALL or REQ_PUT.
            tick_type (int): Greeks calculation basis — only 13 (model price)
                is processed; all other tick types are ignored.
            _tick_attrib (int): Additional tick attributes — not used by this
                implementation.
            implied_vol (float): Implied volatility. Stored as "iv".
            delta (float): Option delta — sensitivity to underlying price.
            _opt_price (float): Model option price — not used by this
                implementation.
            _pv_dividend (float): Present value of dividends — not used by
                this implementation.
            gamma (float): Option gamma — rate of change of delta.
            vega (float): Option vega — sensitivity to implied volatility.
            theta (float): Option theta — daily time decay.
            _und_price (float): Underlying price at computation time — not
                used by this implementation.
        """
        # tick type 13 = model price — most reliable source for Greeks
        if tick_type != 13:
            return

        if req_id == REQ_CALL:
            self.call_data["iv"] = valid_greek(implied_vol)
            self.call_data["delta"] = valid_greek(delta)
            self.call_data["gamma"] = valid_greek(gamma)
            self.call_data["theta"] = valid_greek(theta)
            self.call_data["vega"] = valid_greek(vega)

        elif req_id == REQ_PUT:
            self.put_data["iv"] = valid_greek(implied_vol)
            self.put_data["delta"] = valid_greek(delta)
            self.put_data["gamma"] = valid_greek(gamma)
            self.put_data["theta"] = valid_greek(theta)
            self.put_data["vega"] = valid_greek(vega)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Connect to TWS, subscribe to the ATM option near TARGET_DTE, and stream Greeks.

    Runs the full flow sequentially: connect → get underlying price →
    resolve contract ID → fetch option chain → subscribe → print loop.
    Disconnects cleanly on Ctrl+C or any early exit.
    """
    app = TestConnection()

    try:
        # connect and start the ibapi message loop in a background thread
        app.connect(HOST, PORT, CLIENT_ID)
        api_thread = threading.Thread(target=app.run, daemon=True, name="ibapi")
        api_thread.start()

        # flow step 1 — wait until TWS fires connectAck
        if not app.connected.wait(timeout=10):
            print("Could not connect to TWS — check host, port and API settings")
            return
        print("Connected to TWS")

        # switch to frozen mode — returns last available values when market is closed,
        # falls back to live data automatically when market is open
        app.reqMarketDataType(2)

        # flow step 2 — request IWM underlying price
        # Contract() is an ibapi object — fill in its fields to identify the instrument
        und_contract = Contract()
        und_contract.symbol = SYMBOL
        und_contract.secType = "STK"  # IWM is an ETF (stock type)
        und_contract.exchange = "SMART"  # let IBKR route to the best exchange
        und_contract.currency = "USD"

        app.reqMktData(
            reqId=REQ_UNDERLYING,
            contract=und_contract,
            genericTickList="",  # empty = standard tick types only
            snapshot=False,  # False = keep streaming, True = one-time snapshot
            regulatorySnapshot=False,
            mktDataOptions=[],
        )

        # while we wait, ibapi background thread calls tickPrice() which sets und_price
        if not app.und_ready.wait(timeout=15):
            print("Could not get underlying price — check TWS connection")
            return
        print(f"{SYMBOL} price: {app.und_price}")

        # flow step 3 — look up IWM's internal IBKR contract ID
        # reqSecDefOptParams requires the real numeric ID, not just the symbol
        app.reqContractDetails(
            reqId=REQ_CONTRACT_DETAILS,
            contract=und_contract,
        )

        # while we wait, ibapi background thread calls contractDetails() then contractDetailsEnd()
        # contractDetails() saves the conId, contractDetailsEnd() sets contract_id_ready
        if not app.contract_id_ready.wait(timeout=15):
            print(f"Could not get {SYMBOL} contract ID — check TWS connection")
            return
        if app.underlying_con_id is None:
            print(f"Contract details returned no valid conId for {SYMBOL}")
            return
        print(f"{SYMBOL} contract ID: {app.underlying_con_id}")

        # flow step 4 — request all available expirations and strikes for IWM options
        app.reqSecDefOptParams(
            reqId=REQ_OPT_PARAMS,
            underlyingSymbol=SYMBOL,
            futFopExchange="",  # empty = all exchanges
            underlyingSecType="STK",
            underlyingConId=app.underlying_con_id,  # real contract ID from step 3
        )

        # while we wait, ibapi background thread calls securityDefinitionOptionParameter()
        # once per exchange — we keep only SMART data to avoid duplicates.
        # securityDefinitionOptionParameterEnd() fires last and sets params_ready.
        # by that point app.available_expirations and app.available_strikes are fully populated.
        if not app.params_ready.wait(timeout=15):
            print("Could not get option parameters — check TWS connection")
            return

        # flow step 5 — pick the closest expiry to TARGET_DTE and the ATM strike
        if app.und_price is None:
            print("Underlying price is not set — this should not happen")
            return
        expiry = find_closest_expiry(app.available_expirations, TARGET_DTE)
        strike = find_closest_strike(app.available_strikes, app.und_price)

        if expiry is None:
            print(
                f"No valid expiry found — received {len(app.available_expirations)} "
                f"expirations, all may be expired"
            )
            return
        if strike is None:
            print(
                f"No strike found — received {len(app.available_strikes)} strikes "
                f"for underlying price {app.und_price}"
            )
            return

        today = date.today()
        try:
            expiry_date = expiry_to_date(expiry)
        except ValueError as err:
            print(f"Could not parse selected expiry — {err}")
            return
        dte = (expiry_date - today).days
        print(f"Using expiry {expiry} (DTE {dte})  strike {strike}")

        # flow step 6 — subscribe to market data for the ATM call and put
        # for options, Contract() needs extra fields: expiry, strike, right, multiplier
        for req_id, right in [(REQ_CALL, "C"), (REQ_PUT, "P")]:
            opt_contract = Contract()
            opt_contract.symbol = SYMBOL
            opt_contract.secType = "OPT"
            opt_contract.exchange = "SMART"
            opt_contract.currency = "USD"
            opt_contract.lastTradeDateOrContractMonth = expiry  # e.g. "20260516"
            opt_contract.strike = strike
            opt_contract.right = right  # "C" or "P"
            opt_contract.multiplier = "100"  # 1 contract = 100 shares

            app.reqMktData(
                reqId=req_id,
                contract=opt_contract,
                genericTickList="",
                snapshot=False,
                regulatorySnapshot=False,
                mktDataOptions=[],
            )

        # flow step 7 — print data every 2 seconds until Ctrl+C
        print("\nStreaming data — press Ctrl+C to stop\n")
        while True:
            print_data(SYMBOL, expiry, strike, app.call_data, app.put_data)
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped by user")

    finally:
        # always runs — disconnects cleanly whether stopped by Ctrl+C or an error
        app.disconnect()


if __name__ == "__main__":
    main()
