from dataclasses import dataclass, field


@dataclass
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega:  float = 0.0
    iv:    float = 0.0


@dataclass
class OptionContract:
    strike: float
    expiry: str          # "YYYYMMDD"
    right: str           # "C" or "P"
    greeks: Greeks = field(default_factory=Greeks)
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0


@dataclass
class StrikeSlice:
    """All contracts at a single strike (call + put, one expiry)."""
    strike: float
    expiry: str
    call: OptionContract = field(default_factory=lambda: OptionContract(0, "", "C"))
    put:  OptionContract = field(default_factory=lambda: OptionContract(0, "", "P"))
