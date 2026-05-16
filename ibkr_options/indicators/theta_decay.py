from ..data.options_chain import StrikeSlice


def theta_curve(slices: list[StrikeSlice], right: str) -> list[tuple[float, float]]:
    """Return [(strike, theta), ...] for plotting a theta-vs-strike snapshot.

    right: "C" for calls, "P" for puts
    """
    pass  # TODO: extract theta from each slice and return sorted by strike


def theta_decay_series(history: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Return [(timestamp, theta), ...] showing how theta changed over time
    for a single contract — used to draw the DTE decay curve in the UI.
    """
    pass  # TODO: compute or pass through the time-series data
