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
# note: ibapi is not on PyPI — install it manually first (see ibapi docs),
#       then install the remaining project dependencies:
pip install .
```

## Development

```bash
# install the project together with all dev tools (linter, type checker, etc.)
pip install ".[dev]"

# run all checks at once (Windows PowerShell)
.\drafts\check_all.ps1

# or run individual checks
.\drafts\check_lint.ps1       # ruff lint
.\drafts\check_format.ps1     # ruff formatting
.\drafts\check_types.ps1      # mypy type check
.\drafts\check_docs.ps1       # pydoclint docstrings
.\drafts\check_security.ps1   # bandit + pip-audit
```

## CI

All checks above run automatically on every pull request and push to `master`.

## Project structure

```
drafts/                  # exploratory scripts — not part of the main program
  test_connection.py     # verifies TWS connectivity and basic data flow
  check_all.ps1          # run all checks in sequence and print a summary
  check_lint.ps1         # ruff lint
  check_format.ps1       # ruff format --check
  check_types.ps1        # mypy type check
  check_docs.ps1         # pydoclint docstring check
  check_security.ps1     # bandit security scan + pip-audit CVE check
```

The main program will be added in a separate module as the project grows.
