# Option Advisor

IBKR options data collector and analyzer.

Connects to Interactive Brokers TWS, fetches live option chain data, and streams
Greeks (delta, gamma, theta, vega, IV) for the ATM call and put closest to a target
days-to-expiry.

## Requirements

- Python 3.11
- Interactive Brokers TWS or IB Gateway running locally with API enabled
  (`Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients`)

## Setup

```bash
# create and activate a virtual environment
python -m venv env
.\env\Scripts\Activate.ps1   # Windows PowerShell
source env/bin/activate       # macOS / Linux

# install project dependencies
pip install .
```

## Development

```bash
# install the project together with all dev tools (linter, type checker, etc.)
pip install ".[dev]"

# run all checks
ruff check drafts/test_connection.py            # lint
ruff format --check drafts/test_connection.py   # formatting
mypy drafts/test_connection.py                  # type check
pydoclint --style=google drafts/test_connection.py  # docstrings
bandit -r drafts/test_connection.py             # security scan
pip-audit                                       # dependency CVEs
```

## CI

All checks above run automatically on every pull request and push to `main`.

## Project structure

```
drafts/               # exploratory scripts — not part of the main program
  test_connection.py  # verifies TWS connectivity and basic data flow
```

The main program will be added in a separate module as the project grows.
