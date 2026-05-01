"""Pure-Python Pearson r + linear regression for numeric correlations.

Kept dependency-free so the compute Lambda stays small (no scipy/numpy).
"""

from math import sqrt


def pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Return Pearson r for paired samples, or None if undefined (n<2, zero variance)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    dx2 = 0.0
    dy2 = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my
        num += dx * dy
        dx2 += dx * dx
        dy2 += dy * dy
    denom = sqrt(dx2 * dy2)
    if denom == 0:
        return None
    return num / denom


def linreg(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """OLS slope + intercept for y = slope*x + intercept. None if undefined."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    dx2 = 0.0
    for x, y in zip(xs, ys):
        dx = x - mx
        num += dx * (y - my)
        dx2 += dx * dx
    if dx2 == 0:
        return None
    slope = num / dx2
    intercept = my - slope * mx
    return slope, intercept
