import queue
from .options_chain import StrikeSlice


class DataManager:
    """Consumes updates from the IBKR queue and maintains the current chain snapshot."""

    def __init__(self, data_queue: queue.Queue):
        self._queue = data_queue
        # keyed by (strike, expiry)
        self._chain: dict[tuple, StrikeSlice] = {}  # TODO: parameterise tuple → tuple[float, str]

    def process_pending(self):
        """Drain the queue and apply updates. Call this from the UI timer."""
        pass  # TODO: pull items from self._queue, update self._chain

    def get_chain(self, expiry: str) -> list[StrikeSlice]:
        """Return all strikes for the given expiry, sorted ascending."""
        pass  # TODO: filter and sort self._chain

    def request_chain(self, underlying: str, expiry: str):
        """Ask the connection layer to subscribe to an options chain."""
        pass  # TODO: call IBKRClient to fire reqSecDefOptParams + reqMktData
