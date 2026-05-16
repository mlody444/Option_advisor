# IBKR Options Analyzer — Project Context

## Goal
Build a Python application to analyze options, focusing on theta decay indicators.
The user currently analyzes options by hand and wants tooling to automate/assist this.

## Technology Decisions
- **Broker API:** `ibapi` (official IBKR library) — chosen for full control over `ib_insync`
- **UI:** Start simple (CLI / `tkinter`), expand later
- **Data:** Live Greeks and options chains straight from IBKR TWS/Gateway

## Architecture (4 layers)

```
┌─────────────────────────────────────┐
│           UI / Output Layer         │  (tkinter, CLI, or file export)
├─────────────────────────────────────┤
│         Indicator Layer             │  (theta decay logic, custom math)
├─────────────────────────────────────┤
│         Data Layer                  │  (options chains, Greeks, prices)
├─────────────────────────────────────┤
│         IBKR Connection Layer       │  (ibapi wrapper, callbacks, reconnect)
└─────────────────────────────────────┘
```

### Layer responsibilities

**IBKR Connection Layer**
- Manages connection to TWS/Gateway
- Handles reconnections
- Translates raw callbacks into clean events
- Single point of contact with ibapi — rest of app never touches ibapi directly

**Data Layer**
- Stores options chains per underlying (`StrikePrice`, `Call` classes fit here)
- Refreshes Greeks on schedule or on tick
- Normalises data so the indicator layer doesn't care where data came from

**Indicator Layer**
- Pure Python, no IBKR dependency
- Takes data from Data Layer and computes theta decay curves, P&L projections
- Easiest layer to unit test — no live connection needed

**UI / Output Layer**
- Reads from Indicator Layer
- Start as `print()`, move to `tkinter` later
- Completely swappable without touching anything below

## Key Design Principles
- **Separate IBKR from logic** — indicators work on plain Python objects, not IBKR objects
- **One connection, one thread** — ibapi is not thread-safe
- **Queue between layers** — use `queue.Queue` to pass data from IBKR callback thread safely

## Planned File Structure
```
ibkr_options/
├── connection/
│   ├── ibkr_client.py      # EClient + EWrapper subclass
│   └── reconnect.py        # reconnection logic
├── data/
│   ├── options_chain.py    # Call, StrikePrice classes
│   └── data_manager.py     # stores and refreshes market data
├── indicators/
│   └── theta_decay.py      # custom indicator logic
├── ui/
│   └── display.py          # output / GUI
└── main.py                 # entry point, wires everything together
```

## Existing Code (Python_test folder)
- `test_class_4.py` — `Call` and `StrikePrice` classes (foundation for Data Layer)
- `clock.py` — countdown timer with pygame sound alert
- `requests_test.py` — REST API practice (PokeAPI)

## Next Steps (to continue in new session)
1. Set up `ibkr_options/` folder structure
2. Implement `ibkr_client.py` — EClient + EWrapper subclass
3. Request a live options chain for a chosen underlying
4. Feed Greeks into the Data Layer classes
5. Build first theta decay indicator
