class ReconnectHandler:
    """Watches the connection state and re-establishes it after drops."""

    def __init__(self, client, interval_seconds=30):
        self._client = client
        self._interval = interval_seconds

    def start(self):
        pass  # TODO: start background thread that monitors connection

    def stop(self):
        pass  # TODO: signal the monitor thread to exit

    def on_disconnect(self):
        pass  # TODO: schedule a reconnect attempt after self._interval
