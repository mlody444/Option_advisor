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

import threading
import time
from datetime import date

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract


# ── TWS connection settings ───────────────────────────────────────────────────
HOST       = "127.0.0.1"
PORT       = 5931
CLIENT_ID  = 10        # any number not used by other connections
SYMBOL     = "IWM"
TARGET_DTE = 7         # find the expiry closest to this number of days


# ── request ID constants ──────────────────────────────────────────────────────
REQ_UNDERLYING       = 1
REQ_OPT_PARAMS       = 2
REQ_CALL             = 3
REQ_PUT              = 4
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
    502:   "Cannot connect to TWS — check that TWS is running and API is enabled (Edit → Global Configuration → API → Settings)",
    504:   "Not connected — request was sent before connection was established",
    200:   "No security definition found — check symbol, exchange, or contract details",
    354:   "Requested market data not subscribed — check your IBKR market data subscriptions",
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


# ── helpers ───────────────────────────────────────────────────────────────────

# ibapi sends this when a Greek cannot be computed — no real option Greek exceeds 1e6
IBKR_UNSET_THRESHOLD = 1e6


def valid_greek(value: float | None) -> float | None:
    """Return None if ibapi sent the 'not available' sentinel, otherwise the value."""
    if value is None:
        return None
    if value != value:              # NaN != NaN is the only case where this holds (IEEE 754)
        return None
    if abs(value) > IBKR_UNSET_THRESHOLD:
        return None
    return value


def expiry_to_date(expiry_str: str) -> date:
    """Convert an IBKR expiry string (YYYYMMDD) to a Python date object."""
    try:
        expiry_year  = int(expiry_str[0:4])
        expiry_month = int(expiry_str[4:6])
        expiry_day   = int(expiry_str[6:8])
        return date(expiry_year, expiry_month, expiry_day)
    except (ValueError, TypeError) as e:
        raise ValueError("expiry_to_date: could not parse '{}' — expected YYYYMMDD format".format(expiry_str)) from e


def find_closest_expiry(expirations: set[str], target_dte: int) -> str | None:
    """Return the expiry (YYYYMMDD) whose DTE is closest to target_dte."""
    today         = date.today()
    best_expiry   = None
    best_distance = float("inf")

    for expiry_str in expirations:
        try:
            expiry_date = expiry_to_date(expiry_str)
        except ValueError as e:
            print("find_closest_expiry: skipping bad expiry string — {}".format(e))
            continue

        dte = (expiry_date - today).days

        if dte < 0:
            continue   # skip already-expired entries

        distance = abs(dte - target_dte)

        if distance < best_distance:
            best_distance = distance
            best_expiry   = expiry_str

    return best_expiry


def find_closest_strike(strikes: set[float], und_price: float) -> float | None:
    """Return the available strike closest to the underlying price."""
    best_strike   = None
    best_distance = float("inf")

    for strike in strikes:
        distance = abs(strike - und_price)
        if distance < best_distance:
            best_distance = distance
            best_strike   = strike

    return best_strike


def print_data(symbol: str, expiry: str, strike: float, call_data: dict, put_data: dict):
    """Print the latest call and put Greeks and prices."""
    print("\n--- {} {} strike {}  ({}) ---".format(
        symbol, expiry, strike, time.strftime("%H:%M:%S")
    ))

    # explicit None check: lets genuine 0.0 values (e.g. zero bid, zero delta) pass through
    # as-is instead of being treated as "no data" by the truthiness-based `or` operator.
    # fallback is 0.0 (not 0) so round() always returns float — round(0, 4) returns int in Python
    def fmt(key: str, data: dict, digits: int) -> float:
        value = data.get(key)
        return round(value if value is not None else 0.0, digits)

    for label, data in [("CALL", call_data), ("PUT", put_data)]:
        print("  {}  bid={:>8}  ask={:>8}  iv={:>7}  delta={:>7}  gamma={:>7}  theta={:>8}  vega={:>7}".format(
            label,
            fmt("bid",   data, 2),
            fmt("ask",   data, 2),
            fmt("iv",    data, 4),
            fmt("delta", data, 4),
            fmt("gamma", data, 4),
            fmt("theta", data, 4),
            fmt("vega",  data, 4),
        ))


# ── ibapi callbacks ───────────────────────────────────────────────────────────

class TestConnection(EWrapper, EClient):
    """
    Receives ibapi callbacks (EWrapper) and sends requests (EClient).
    The same object plays both roles, so EClient receives 'self' as its wrapper.
    All collected state is stored as plain attributes and read by main().
    """

    def __init__(self):
        EWrapper.__init__(self)
        EClient.__init__(self, self)  # pass self as wrapper — same object handles callbacks

        # underlying price
        self.und_price = None
        self.und_ready = threading.Event()

        # available option chain from IBKR
        self.available_expirations = set()
        self.available_strikes     = set()
        self.params_ready          = threading.Event()

        # latest data for the ATM call and put (filled by callbacks)
        self.call_data = {}
        self.put_data  = {}

        # set when TWS confirms the connection is established
        self.connected = threading.Event()

        # IWM's internal IBKR contract ID — needed for reqSecDefOptParams
        self.underlying_con_id = None
        self.contract_id_ready = threading.Event()

    # ── connection (flow step 1) ──────────────────────────────────────────────

    # ibapi's 2000-2999 range = status notifications (data farm connected, etc.)
    # using range() means any new 2xxx code ibapi adds is handled automatically.
    # subclass can override with a different range or a specific tuple if needed.
    INFO_CODES = range(2000, 3000)

    # fired by ibapi once after connect() succeeds — confirms the session is live
    def connectAck(self):
        self.connected.set()

    # fired by ibapi after reqMarketDataType() to confirm which mode is now active
    def marketDataType(self, _, market_data_type):
        names = {
            1: "live",
            2: "frozen (last values — used when market is closed)",
            3: "delayed 15 min",
            4: "delayed frozen",
        }
        name = names.get(market_data_type, str(market_data_type))
        print("Market data mode: {}".format(name))

    # fired by ibapi for every error AND every status notification — both come through here
    def error(self, req_id, _error_time, error_code, error_string, _advanced_order_reject_desc=""):
        # silently ignore status notifications — they are not errors
        if error_code in self.INFO_CODES:
            return
        # use our plain-English description if available, otherwise ibapi's own message
        description = KNOWN_ERRORS.get(error_code, error_string)
        print("IBKR error {} (req {}): {}".format(error_code, req_id, description))

    # ── underlying price (flow step 2) ───────────────────────────────────────

    # fired by ibapi for every price tick from reqMktData() — underlying, call, and put
    def tickPrice(self, req_id, tick_type, price, _attrib):
        if price <= 0:
            return

        if req_id == REQ_UNDERLYING:
            print("DEBUG tick — type: {}  price: {}".format(tick_type, price))
            # tick type 4 = last traded price
            # tick type 9 = close price — only used as fallback when market is closed
            if tick_type == 4 or (tick_type == 9 and self.und_price is None):
                self.und_price = price
                self.und_ready.set()

        elif req_id == REQ_CALL:
            if tick_type == 1: self.call_data["bid"]  = price
            if tick_type == 2: self.call_data["ask"]  = price
            if tick_type == 4: self.call_data["last"] = price

        elif req_id == REQ_PUT:
            if tick_type == 1: self.put_data["bid"]  = price
            if tick_type == 2: self.put_data["ask"]  = price
            if tick_type == 4: self.put_data["last"] = price

    # ── contract ID (flow step 3) ─────────────────────────────────────────────

    # fired by ibapi for each result returned by reqContractDetails()
    # one call per matching contract — IBKR may return several for ambiguous symbols
    def contractDetails(self, req_id, contract_details):
        if req_id != REQ_CONTRACT_DETAILS:
            return
        if self.underlying_con_id is not None:
            return   # already stored the first valid result — ignore subsequent ones
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
    def contractDetailsEnd(self, req_id):
        if req_id == REQ_CONTRACT_DETAILS:
            self.contract_id_ready.set()

    # ── option params (flow step 4) ───────────────────────────────────────────

    # fired by ibapi once per exchange in response to reqSecDefOptParams()
    # delivers all available expirations and strikes for that exchange
    def securityDefinitionOptionParameter(self, req_id, exchange,
                                           _underlying_con_id, _trading_class,
                                           _multiplier, expirations, strikes):
        if req_id != REQ_OPT_PARAMS:
            return
        print("DEBUG params — exchange: {}  expirations: {}  strikes: {}".format(
            exchange, len(expirations), len(strikes)
        ))
        # we only keep SMART exchange data to avoid duplicates
        if exchange == "SMART":
            self.available_expirations.update(expirations)
            self.available_strikes.update(strikes)

    # fired by ibapi once after all securityDefinitionOptionParameter() calls are done
    # only now is it safe to read available_expirations and available_strikes
    def securityDefinitionOptionParameterEnd(self, req_id):
        if req_id != REQ_OPT_PARAMS:
            return
        print("DEBUG params end — total expirations: {}  total strikes: {}".format(
            len(self.available_expirations), len(self.available_strikes)
        ))
        self.params_ready.set()

    # ── option Greeks (flow step 6) ───────────────────────────────────────────

    # fired by ibapi for every Greeks tick from reqMktData() on an option contract
    def tickOptionComputation(self, req_id, tick_type, _tick_attrib,
                              implied_vol, delta, _opt_price, _pv_dividend,
                              gamma, vega, theta, _und_price):
        # tick type 13 = model price — most reliable source for Greeks
        if tick_type != 13:
            return

        if req_id == REQ_CALL:
            self.call_data["iv"]    = valid_greek(implied_vol)
            self.call_data["delta"] = valid_greek(delta)
            self.call_data["gamma"] = valid_greek(gamma)
            self.call_data["theta"] = valid_greek(theta)
            self.call_data["vega"]  = valid_greek(vega)

        elif req_id == REQ_PUT:
            self.put_data["iv"]    = valid_greek(implied_vol)
            self.put_data["delta"] = valid_greek(delta)
            self.put_data["gamma"] = valid_greek(gamma)
            self.put_data["theta"] = valid_greek(theta)
            self.put_data["vega"]  = valid_greek(vega)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
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
        und_contract          = Contract()
        und_contract.symbol   = SYMBOL
        und_contract.secType  = "STK"    # IWM is an ETF (stock type)
        und_contract.exchange = "SMART"  # let IBKR route to the best exchange
        und_contract.currency = "USD"

        app.reqMktData(
            reqId              = REQ_UNDERLYING,
            contract           = und_contract,
            genericTickList    = "",      # empty = standard tick types only
            snapshot           = False,   # False = keep streaming, True = one-time snapshot
            regulatorySnapshot = False,
            mktDataOptions     = [],
        )

        # while we wait, ibapi background thread calls tickPrice() which sets und_price
        if not app.und_ready.wait(timeout=15):
            print("Could not get underlying price — check TWS connection")
            return
        print("{} price: {}".format(SYMBOL, app.und_price))

        # flow step 3 — look up IWM's internal IBKR contract ID
        # reqSecDefOptParams requires the real numeric ID, not just the symbol
        app.reqContractDetails(
            reqId    = REQ_CONTRACT_DETAILS,
            contract = und_contract,
        )

        # while we wait, ibapi background thread calls contractDetails() then contractDetailsEnd()
        # contractDetails() saves the conId, contractDetailsEnd() sets contract_id_ready
        if not app.contract_id_ready.wait(timeout=15):
            print("Could not get {} contract ID — check TWS connection".format(SYMBOL))
            return
        if app.underlying_con_id is None:
            print("Contract details returned no valid conId for {} — contract may be ambiguous".format(SYMBOL))
            return
        print("{} contract ID: {}".format(SYMBOL, app.underlying_con_id))

        # flow step 4 — request all available expirations and strikes for IWM options
        app.reqSecDefOptParams(
            reqId             = REQ_OPT_PARAMS,
            underlyingSymbol  = SYMBOL,
            futFopExchange    = "",                     # empty = all exchanges
            underlyingSecType = "STK",
            underlyingConId   = app.underlying_con_id,  # real contract ID from step 3
        )

        # while we wait, ibapi background thread calls securityDefinitionOptionParameter()
        # once per exchange — we keep only SMART data to avoid duplicates.
        # securityDefinitionOptionParameterEnd() fires last and sets params_ready.
        # by that point app.available_expirations and app.available_strikes are fully populated.
        if not app.params_ready.wait(timeout=15):
            print("Could not get option parameters — check TWS connection")
            return

        # flow step 5 — pick the closest expiry to TARGET_DTE and the ATM strike
        expiry = find_closest_expiry(app.available_expirations, TARGET_DTE)
        strike = find_closest_strike(app.available_strikes, app.und_price)

        if expiry is None:
            print("No valid expiry found — received {} expirations, all may be expired".format(
                len(app.available_expirations)
            ))
            return
        if strike is None:
            print("No strike found — received {} strikes for underlying price {}".format(
                len(app.available_strikes), app.und_price
            ))
            return

        today = date.today()
        try:
            expiry_date = expiry_to_date(expiry)
        except ValueError as e:
            print("Could not parse selected expiry — {}".format(e))
            return
        dte = (expiry_date - today).days
        print("Using expiry {} (DTE {})  strike {}".format(expiry, dte, strike))

        # flow step 6 — subscribe to market data for the ATM call and put
        # for options, Contract() needs extra fields: expiry, strike, right, multiplier
        for req_id, right in [(REQ_CALL, "C"), (REQ_PUT, "P")]:
            opt_contract                              = Contract()
            opt_contract.symbol                       = SYMBOL
            opt_contract.secType                      = "OPT"
            opt_contract.exchange                     = "SMART"
            opt_contract.currency                     = "USD"
            opt_contract.lastTradeDateOrContractMonth = expiry    # e.g. "20260516"
            opt_contract.strike                       = strike
            opt_contract.right                        = right     # "C" or "P"
            opt_contract.multiplier                   = "100"     # 1 contract = 100 shares

            app.reqMktData(
                reqId              = req_id,
                contract           = opt_contract,
                genericTickList    = "",
                snapshot           = False,
                regulatorySnapshot = False,
                mktDataOptions     = [],
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
