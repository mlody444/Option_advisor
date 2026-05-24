from ibapi.client import EClient
from ibapi.wrapper import EWrapper


class IBKRClient(EWrapper, EClient):
    """Single point of contact with ibapi. All callbacks are handled here.
    No other module imports from ibapi directly.
    """

    # TODO: add type hints to all methods (no -> None, no parameter types)

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

    # TODO: wrong signature — ibapi 10.30+ inserts error_time as 2nd parameter.
    #       correct order: (self, req_id, error_time, error_code, error_string,
    #                       advanced_order_reject_desc)
    #       see drafts/test_connection.py error() for reference
    def error(self, req_id, error_code, error_string, advanced_order_reject_desc=""):
        pass  # TODO: log and route to reconnect logic if needed

    def tickOptionComputation(self, req_id, tick_type, tick_attrib,
                              implied_vol, delta, opt_price, pv_dividend,
                              gamma, vega, theta, und_price):
        pass  # TODO: package Greeks and push to self._queue

    # TODO: wrong callback name — ibapi calls securityDefinitionOptionParameter (no "al")
    #       this override is never invoked; option params will silently never arrive
    def securityDefinitionOptionalParameter(self, req_id, exchange,
                                            underlying_con_id, trading_class,
                                            multiplier, expirations, strikes):
        pass  # TODO: forward available strikes/expirations to data layer
