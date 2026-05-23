import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ── data structures passed in by the collector ────────────────────────────────

@dataclass
class OptionSide:
    """Greeks and price data for one side (call or put) at one strike."""
    bid:   float | None
    ask:   float | None
    last:  float | None
    iv:    float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega:  float | None


@dataclass
class StrikeRow:
    """One row in the CSV — call side, strike price, put side."""
    strike: float
    call:   OptionSide
    put:    OptionSide


@dataclass
class ExpiryBlock:
    """All strike rows for a single expiry date."""
    expiry: str          # format: YYYYMMDD  (used internally, converted for filenames)
    dte:    int          # days to expiration at snapshot time
    tier:   str          # hot / warm / cold
    rows:   list[StrikeRow]


@dataclass
class Snapshot:
    """Everything collected in one snapshot run."""
    symbol:      str
    timestamp:   datetime
    und_price:   float          # underlying price at snapshot time
    und_bid:     float | None   # underlying bid
    und_ask:     float | None   # underlying ask
    vix:         float | None   # VIX index value
    atm_iv:      float | None   # 30-day ATM implied volatility
    expirations: list[ExpiryBlock]


# ── CSV column headers ────────────────────────────────────────────────────────

CALL_COLUMNS = [
    "call_bid", "call_ask", "call_last",
    "call_iv", "call_delta", "call_gamma", "call_theta", "call_vega",
]

PUT_COLUMNS = [
    "put_bid", "put_ask", "put_last",
    "put_iv", "put_delta", "put_gamma", "put_theta", "put_vega",
]

# final column order in every CSV: call side | strike | put side
ALL_COLUMNS = CALL_COLUMNS + ["strike"] + PUT_COLUMNS


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(value: float | None) -> str:
    """Format a number for output. Returns empty string if data is missing."""
    if value is None:
        return ""
    return str(round(value, 6))


def _expiry_to_readable(expiry: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD for use in filenames and the info file."""
    return "{}-{}-{}".format(expiry[0:4], expiry[4:6], expiry[6:8])


def _side_to_dict(side: OptionSide, prefix: str) -> dict:  # TODO: ruff format — column-aligned assignments inside will be reformatted
    """
    Convert one option side to a flat dictionary.
    prefix is either 'call_' or 'put_'.
    """
    result = {}
    result[prefix + "bid"]   = _fmt(side.bid)
    result[prefix + "ask"]   = _fmt(side.ask)
    result[prefix + "last"]  = _fmt(side.last)
    result[prefix + "iv"]    = _fmt(side.iv)
    result[prefix + "delta"] = _fmt(side.delta)
    result[prefix + "gamma"] = _fmt(side.gamma)
    result[prefix + "theta"] = _fmt(side.theta)
    result[prefix + "vega"]  = _fmt(side.vega)
    return result


# ── main entry point ──────────────────────────────────────────────────────────

def write_snapshot(snapshot: Snapshot, output_dir: Path,
                   highest_strike_first: bool = True) -> Path:
    """
    Write the full snapshot to disk.
    Creates one folder containing one CSV per expiry and a summary txt file.
    Returns the path of the created folder.

    highest_strike_first: if True (default) rows are written highest strike on top,
                          set to False to reverse the order.
    """

    # folder name example: SPX_2026-05-10_09-31-00
    folder_name = "{}_{}".format(
        snapshot.symbol,
        snapshot.timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
    )
    folder = output_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    # write one CSV file per expiry
    for block in snapshot.expirations:
        _write_expiry_csv(folder, block, highest_strike_first)

    # write the human-readable summary file
    _write_info_txt(folder, snapshot)

    return folder


# ── CSV writer ────────────────────────────────────────────────────────────────

def _write_expiry_csv(folder: Path, block: ExpiryBlock,
                      highest_strike_first: bool) -> None:
    """
    Write a single expiry to its own CSV file.
    Filename example: DTE_033_2026-06-12.csv
    Each row = one strike, with call data on the left and put data on the right.
    """
    readable_date = _expiry_to_readable(block.expiry)
    filename = "DTE_{:03d}_{}.csv".format(block.dte, readable_date)
    filepath = folder / filename

    # sort strikes: highest on top by default, lowest on top if reversed
    sorted_rows = sorted(block.rows, key=lambda row: row.strike,
                         reverse=highest_strike_first)

    with open(filepath, "w", newline="") as f:
        # fieldnames defines both the header row and the column order
        writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS)
        writer.writeheader()

        for row in sorted_rows:
            csv_row = {}

            # left side: call Greeks and prices
            csv_row.update(_side_to_dict(row.call, "call_"))

            # middle: strike price
            csv_row["strike"] = row.strike

            # right side: put Greeks and prices
            csv_row.update(_side_to_dict(row.put, "put_"))

            writer.writerow(csv_row)


# ── info txt writer ───────────────────────────────────────────────────────────

def _write_info_txt(folder: Path, snapshot: Snapshot) -> None:
    """Write snapshot_info.txt with market context and capture summary."""

    filepath = folder / "snapshot_info.txt"

    # total contracts = each strike row has 2 sides (call + put)
    total_contracts = sum(len(block.rows) * 2 for block in snapshot.expirations)

    with open(filepath, "w") as f:

        f.write("=== SNAPSHOT INFO ===\n")
        f.write("Symbol          : {}\n".format(snapshot.symbol))
        f.write("Snapshot time   : {}\n".format(
            snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        ))
        f.write("\n")

        f.write("=== UNDERLYING ===\n")
        f.write("Price           : {}\n".format(_fmt(snapshot.und_price)))
        f.write("Bid / Ask       : {} / {}\n".format(
            _fmt(snapshot.und_bid), _fmt(snapshot.und_ask)
        ))
        f.write("\n")

        f.write("=== VOLATILITY SUMMARY ===\n")
        f.write("VIX             : {}\n".format(
            "{:.2f}".format(snapshot.vix) if snapshot.vix is not None else "N/A"
        ))
        f.write("30-day ATM IV   : {}\n".format(
            "{:.4f}".format(snapshot.atm_iv) if snapshot.atm_iv is not None else "N/A"
        ))
        f.write("\n")

        f.write("=== IV TERM STRUCTURE (ATM IV per expiry) ===\n")
        for block in snapshot.expirations:
            if not block.rows:
                continue

            # find the strike row closest to underlying price (ATM)
            atm_row = None
            min_distance = float("inf")
            for row in block.rows:
                distance = abs(row.strike - snapshot.und_price)
                if distance < min_distance:
                    min_distance = distance
                    atm_row = row

            iv_str = "{:.4f}".format(atm_row.call.iv) if atm_row.call.iv is not None else "N/A"
            readable_date = _expiry_to_readable(block.expiry)
            f.write("  DTE_{:03d}  {}   IV: {}\n".format(block.dte, readable_date, iv_str))

        f.write("\n")

        f.write("=== CAPTURE SUMMARY ===\n")
        f.write("Expirations     : {}\n".format(len(snapshot.expirations)))
        f.write("Total contracts : {}\n".format(total_contracts))
