import queue

from ibkr_options.connection.ibkr_client import IBKRClient
from ibkr_options.connection.reconnect import ReconnectHandler
from ibkr_options.data.data_manager import DataManager
from ibkr_options.ui.display import run

HOST      = "127.0.0.1"
PORT      = 7497   # 7496 for TWS live, 7497 for TWS paper, 4001/4002 for Gateway
CLIENT_ID = 1


def main():
    data_queue = queue.Queue()

    client    = IBKRClient(data_queue)
    reconnect = ReconnectHandler(client)
    dm        = DataManager(data_queue)

    client.connect_and_run(HOST, PORT, CLIENT_ID)
    reconnect.start()

    run(dm)   # blocks until window is closed


if __name__ == "__main__":
    main()
