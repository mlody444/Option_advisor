import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Tier:
    name: str             # hot / warm / cold
    dte_max: int          # upper DTE boundary (inclusive)
    strike_count: int     # max strikes to capture per expiry
    atm_range_pct: float  # ± fraction of underlying price defining the window

    def strikes_for(self, und_price: float, available: list[float]) -> list[float]:
        """Return filtered strikes for this tier given current underlying price.

        1. Keep only strikes within ±atm_range_pct of und_price.
        2. If more remain than strike_count, keep the nearest ones to ATM.
        3. Return sorted ascending.
        """
        lo = und_price * (1 - self.atm_range_pct)
        hi = und_price * (1 + self.atm_range_pct)
        in_range = [s for s in available if lo <= s <= hi]

        if len(in_range) > self.strike_count:
            in_range = sorted(in_range, key=lambda s: abs(s - und_price))[: self.strike_count]

        return sorted(in_range)


@dataclass
class LoggerConfig:
    symbol: str
    output_dir: Path
    tiers: list[Tier]

    def tier_for_dte(self, dte: int) -> Tier | None:
        """Return the matching tier for a given DTE, or None if beyond all tiers."""
        for tier in self.tiers:
            if dte <= tier.dte_max:
                return tier
        return None


def load(path: str | Path = "logger_config.json") -> LoggerConfig:
    raw = json.loads(Path(path).read_text())

    tiers = [
        Tier(
            name=t["name"],
            dte_max=t["dte_max"],
            strike_count=t["strike_count"],
            atm_range_pct=t["atm_range_pct"],
        )
        for t in raw["tiers"]
    ]
    tiers.sort(key=lambda t: t.dte_max)   # ensure hot → cold order

    return LoggerConfig(
        symbol=raw["symbol"],
        output_dir=Path(raw["output_dir"]),
        tiers=tiers,
    )
