# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Connects to Interactive Brokers TWS via ibapi, fetches live option chain data, and streams Greeks (delta, gamma, theta, vega, IV) for the ATM call and put closest to a target days-to-expiry. The main entry point is `drafts/test_connection.py`; a production module will grow from there.

## Environment

- Python 3.11 (pinned in `.python-version`)
- **ibapi is not on PyPI** — must be installed manually. `tests/conftest.py` auto-mocks it when missing, so unit/integration/qualification tests run without it.
- Windows dev machine with WSL for mutation testing. Activate the Windows venv with `.\env\Scripts\Activate.ps1`.
- Mutation testing uses a WSL-native venv at `~/.venv-option-advisor` (avoids `/mnt/` performance issues). Never use the Windows venv path for mutmut.

## Common commands

All checks have PowerShell wrappers in `drafts/`. Run from the project root.

```powershell
.\drafts\check_all.ps1        # run every check including mutation testing (slow)
.\drafts\check_quick.ps1      # fast checks only (lint, format, types, docs, tests)
.\drafts\check_tests.ps1      # pytest unit + integration + qualification (not live)
.\drafts\check_mutmut.ps1     # mutation testing via WSL
```

Individual checks:
```powershell
.\drafts\check_lint.ps1       # ruff lint
.\drafts\check_format.ps1     # ruff format --check
.\drafts\check_types.ps1      # mypy (strict)
.\drafts\check_docs.ps1       # pydoclint (Google style)
.\drafts\check_security.ps1   # bandit + pip-audit
```

Run a single test file or test:
```powershell
python -m pytest tests/unit/test_ibkr_utils.py -v
python -m pytest tests/unit/test_ibkr_utils.py::TestExpiryToDate::test_valid_date -v
```

Validate Hypothesis example counts (profile-aware):
```powershell
pytest tests/unit/ --hypothesis-show-statistics   # local: expect 10 examples
$env:HYPOTHESIS_PROFILE = "ci"; pytest tests/unit/ --hypothesis-show-statistics   # CI: expect 50
```

## Architecture

### `drafts/` — active development area

This is where new code is written and proven before promotion. It is **not** distributed (excluded from the package by `setuptools`).

- **`test_connection.py`** — the current main program. Connects to TWS and streams option Greeks. The `TestConnection` class combines `EWrapper` (receives callbacks) and `EClient` (sends requests) into a single object. Data flows through `threading.Event` gates: `connected` → `und_ready` → `contract_id_ready` → `params_ready`, then a print loop every 2 s.
- **`ibkr_utils.py`** — pure utility functions with no ibapi dependency. Extracted from `test_connection.py` so they can be unit-tested. Currently: `valid_greek`, `expiry_to_date`, `find_closest_expiry`, `find_closest_strike`, `print_data`.
- **`ui_demo.py`** — PyQt6/pyqtgraph UI prototype showing theta decay charts per strike. Standalone mock data, no TWS connection needed.

### ibapi threading model

ibapi requires a background thread running `app.run()` to process the message loop. All callbacks (`tickPrice`, `tickOptionComputation`, etc.) fire on that thread. The main thread communicates via `threading.Event` and plain dict/set attributes (no locking — writes happen in callbacks, reads happen after the corresponding Event is set).

### `drafts/ibkr_utils.py` and its tests

`ibkr_utils.py` is the unit-testable layer. All functions are pure (no ibapi calls). Key ibapi quirks encoded here:
- `valid_greek()` — ibapi sends `None`, `NaN`, or `abs(x) > 1e6` when a Greek is unavailable.
- `expiry_to_date()` — parses YYYYMMDD strings; slices are fixed (`[0:4]`, `[4:6]`, `[6:8]`).
- `find_closest_expiry()` / `find_closest_strike()` — use `<` (not `<=`) so the first equal-distance entry wins.

### `tests/` — test suite (ASPICE SWE.4 / SWE.5 / SWE.6)

The test suite is structured around three ASPICE process levels:

| Directory | ASPICE level | Scope |
|---|---|---|
| `tests/unit/` | SWE.4 — Software Unit Verification | Pure functions, no TWS, no network. Runs in CI with mutation testing. |
| `tests/integration/` | SWE.5 — Software Integration Test | Tests across module boundaries against mocked ibapi seams. Currently being developed. |
| `tests/qualification/` | SWE.6 — Software Qualification Test | End-to-end behaviour. `@pytest.mark.live` tests require real TWS and are excluded from CI. |

```
tests/
  conftest.py          # ibapi mock + Hypothesis profiles (local=10, ci=50 examples)
  unit/                # SWE.4
  integration/         # SWE.5
  qualification/       # SWE.6
```

`conftest.py` auto-mocks all `ibapi.*` submodules when ibapi is not installed. Tests that need a live TWS connection are marked `@pytest.mark.live` and excluded from CI runs.

## Mutation testing

Mutmut v2 is pinned (`mutmut<3`) — v3 has WSL compatibility issues that prevent migration. v3 would allow `--workers N` parallelism.

- Scope: `drafts/ibkr_utils.py` only (configured in `pyproject.toml`)
- Runner: `pytest -x` (fail-fast per mutant)
- The wrapper script (`drafts/check_mutmut.sh`) deletes `.mutmut-cache` before each run because mutmut v2 caches by source hash only — stale when tests change.
- mutmut v2 returns a non-zero exit code even when all mutants are killed. The script works around this by parsing `mutmut results` output and deriving the exit code from survived/suspicious counts.

### Mutation testing patterns

When adding tests to kill surviving mutants:
- **Substring traps**: `pytest.raises(match=...)` uses `re.search` — anchor with `^` to prevent `"XXtext"` from matching `"text"`. Same issue with `assert "text" in out` when `"text"` appears elsewhere (e.g. strike `580.0` contains `"0.0"`).
- **`continue` vs `break` with sets**: sets have non-deterministic iteration — pass a **list** to fix order and make the mutation observable.
- **`<` vs `<=` tie-breaking**: only observable with equal-distance entries in a known order — use a list.
- **`"XX" not in out`**: kills all mutants that wrap output strings in `"XX...XX"` markers.

## Hypothesis profiles

Defined in `tests/conftest.py`, controlled by `HYPOTHESIS_PROFILE` env var:
- `local` (default): 10 examples — fast for local runs and mutmut
- `ci`: 50 examples — set at job level in `.github/workflows/unit_test.yml`

Do not add `@settings(max_examples=N)` to individual tests — let the profile control it globally.
