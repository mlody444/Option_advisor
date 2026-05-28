"""Pure utility functions for IBKR options data — no ibapi dependency."""

import time
from datetime import date

# ibapi sends this sentinel when a Greek cannot be computed — no real option Greek exceeds 1e6
IBKR_UNSET_THRESHOLD = 1e6


def valid_greek(value: float | None) -> float | None:
    """Check if greek value is available.

    ibapi Greek can be unavailable in three ways:
        1. By passing None,
        2. By passing NaN,
        3. By passing large float value (abs > 1000000.0)

    Args:
        value (float | None): Raw Greek value received from ibapi,
            to be validated.

    Returns:
        float | None: The value unchanged (if valid), or None (if not valid).
    """
    if value is None:
        return None
    if value != value:  # NaN != NaN is the only case where this holds (IEEE 754)
        return None
    if abs(value) > IBKR_UNSET_THRESHOLD:
        return None
    return value


def expiry_to_date(expiry_str: str) -> date:
    """Convert an IBKR expiry string (YYYYMMDD) to a Python date object.

    Args:
        expiry_str (str): Expiry string in YYYYMMDD format, e.g. "20260516".
            Must be 8 characters with a numeric year, month, and day.

    Returns:
        date: Python date object representing the expiry date.

    Raises:
        ValueError: If the string is not in YYYYMMDD format, contains
            non-numeric characters, or represents an invalid calendar date.
    """
    try:
        expiry_year = int(expiry_str[0:4])
        expiry_month = int(expiry_str[4:6])
        expiry_day = int(expiry_str[6:8])
        return date(expiry_year, expiry_month, expiry_day)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"expiry_to_date: could not parse '{expiry_str}' — expected YYYYMMDD format"
        ) from e


def find_closest_expiry(expirations: set[str], target_dte: int) -> str | None:
    """Find closest to the target expiry.

    Expired entries (DTE < 0) are skipped
    Malformed strings are skipped with a warning printed to stdout.

    Args:
        expirations (set[str]): Set of expiry strings in YYYYMMDD format
            as returned by reqSecDefOptParams().
        target_dte (int): Target number of days to expiry, e.g. 7.

    Returns:
        str | None: Expiry string closest to target_dte, or None if the
            set is empty or all entries are already expired.
    """
    today = date.today()
    best_expiry = None
    best_distance = float("inf")

    for expiry_str in expirations:
        try:
            expiry_date = expiry_to_date(expiry_str)
        except ValueError as err:
            print(f"find_closest_expiry: skipping bad expiry string — {err}")
            continue

        dte = (expiry_date - today).days

        if dte < 0:
            continue  # skip already-expired entries

        distance = abs(dte - target_dte)

        if distance < best_distance:
            best_distance = distance
            best_expiry = expiry_str

    return best_expiry


def find_closest_strike(strikes: set[float], und_price: float) -> float | None:
    """Find the listed strike price closest to the underlying price (ATM).

    Args:
        strikes (set[float]): Set of available strike prices as returned
            by reqSecDefOptParams().
        und_price (float): Current underlying price used as the ATM reference.

    Returns:
        float | None: Strike price closest to und_price, or None if the
            set is empty.
    """
    best_strike = None
    best_distance = float("inf")

    for strike in strikes:
        distance = abs(strike - und_price)
        if distance < best_distance:
            best_distance = distance
            best_strike = strike

    return best_strike


def print_data(
    symbol: str,
    expiry: str,
    strike: float,
    call_data: dict[str, float | None],
    put_data: dict[str, float | None],
) -> None:
    """Print the latest call and put Greeks and prices.

    Called every 2 seconds from the main loop. Missing values (keys not
    yet received from ibapi) display as 0.

    Args:
        symbol (str): Underlying ticker symbol, e.g. "IWM".
        expiry (str): Option expiry string in YYYYMMDD format.
        strike (float): Strike price of the subscribed contracts.
        call_data (dict[str, float | None]): Latest call fields keyed by name — bid, ask,
            iv, delta, gamma, theta, vega. Missing keys display as 0.
        put_data (dict[str, float | None]): Latest put fields — same structure as call_data.
    """
    print(f"\n--- {symbol} {expiry} strike {strike}  ({time.strftime('%H:%M:%S')}) ---")

    def fmt(key: str, data: dict[str, float | None], digits: int, width: int) -> str:
        value = data.get(key)
        if key not in data:
            return f"{'---':>{width}}"
        if value is None:
            return f"{'N/A':>{width}}"
        return f"{round(value, digits):>{width}}"

    for label, data in [("CALL", call_data), ("PUT", put_data)]:
        print(
            f"  {label}"
            f"  bid={fmt('bid', data, 2, 8)}"
            f"  ask={fmt('ask', data, 2, 8)}"
            f"  iv={fmt('iv', data, 4, 7)}"
            f"  delta={fmt('delta', data, 4, 7)}"
            f"  gamma={fmt('gamma', data, 4, 7)}"
            f"  theta={fmt('theta', data, 4, 8)}"
            f"  vega={fmt('vega', data, 4, 7)}"
        )
