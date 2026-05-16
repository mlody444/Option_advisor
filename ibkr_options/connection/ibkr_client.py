from ibapi.client import EClient
from ibapi.wrapper import EWrapper


class IBKRClient(EWrapper, EClient):
    """Single point of contact with ibapi. All callbacks are handled here.
    No other module imports from ibapi directly.
    """

    def __init__(self, data_queue):
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self._queue = data_queue

    # ── connection ────────────────────────────────────────────────────────────

    def connect_and_run(self, host="127.0.0.1", port=7497, client_id=1):
        pass  # TODO: connect, start reader thread, call run()

    def disconnect_gracefully(self):
        pass  # TODO: cancel subscriptions, then disconnect()

    # ── EWrapper callbacks ────────────────────────────────────────────────────

    def error(self, req_id, error_code, error_string, advanced_order_reject_desc=""):
        pass  # TODO: log and route to reconnect logic if needed

    def tickOptionComputation(self, req_id, tick_type, tick_attrib,
                              implied_vol, delta, opt_price, pv_dividend,
                              gamma, vega, theta, und_price):
        pass  # TODO: package Greeks and push to self._queue

    def securityDefinitionOptionalParameter(self, req_id, exchange,
                                            underlying_con_id, trading_class,
                                            multiplier, expirations, strikes):
        pass  # TODO: forward available strikes/expirations to data layer
