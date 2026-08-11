"""Link-stability metrics for CHIRP Module 1.

Link Expiration Time (LET) follows Su & Zhang's closed form, the standard
mobility-prediction metric in VANET clustering. For nodes i, j with positions
(x, y) and velocity components, and transmission range R:

    a = vx_i - vx_j        b = x_i - x_j
    c = vy_i - vy_j        d = y_i - y_j

    LET = [ -(ab + cd) + sqrt((a^2 + c^2) R^2 - (ad - bc)^2) ] / (a^2 + c^2)

LET is the time until the pair drifts out of range if both hold their current
velocity. When a^2 + c^2 = 0 the pair is moving identically and the link never
expires, so LET is infinite (we clamp to a horizon).

Nothing in the base paper predicts link lifetime -- CH selection there is
energy-and-distance only, which is why its clusters dissolve as soon as the
static assumption is dropped.
"""

from __future__ import annotations

import numpy as np


def link_expiration_time(pos_i, vel_i, pos_j, vel_j, tx_range, horizon=1e3):
    """Pairwise LET. Broadcasts, so pass (M,1,2) against (1,N,2) for a matrix."""
    b = pos_i[..., 0] - pos_j[..., 0]
    d = pos_i[..., 1] - pos_j[..., 1]
    a = vel_i[..., 0] - vel_j[..., 0]
    c = vel_i[..., 1] - vel_j[..., 1]

    denom = a**2 + c**2
    disc = denom * tx_range**2 - (a * d - b * c) ** 2

    with np.errstate(invalid="ignore", divide="ignore"):
        let = (-(a * b + c * d) + np.sqrt(np.maximum(disc, 0.0))) / denom

    # identical velocity -> link never breaks; negative -> already separating
    let = np.where(denom < 1e-12, horizon, let)
    let = np.where(disc < 0, 0.0, let)
    return np.clip(let, 0.0, horizon)


def normalise(x, lo=None, hi=None):
    """Scale to [0,1]; constant input maps to 1.0 (no discrimination)."""
    x = np.asarray(x, dtype=float)
    lo = float(np.min(x)) if lo is None else lo
    hi = float(np.max(x)) if hi is None else hi
    if hi - lo < 1e-12:
        return np.ones_like(x)
    return (x - lo) / (hi - lo)


def weighted_percentile(samples, q: float) -> float:
    """Percentile over (value, weight) pairs.

    Delay is recorded once per cluster per round with the number of readings
    that experienced it as the weight, so the weights must be honoured -- a
    12-member cluster contributes twelve times what a 1-member cluster does.
    """
    if not samples:
        return float("nan")
    v = np.array([s[0] for s in samples], dtype=float)
    w = np.array([s[1] for s in samples], dtype=float)
    keep = w > 0
    if not keep.any():
        return float("nan")
    v, w = v[keep], w[keep]
    order = np.argsort(v)
    v, w = v[order], w[order]
    c = np.cumsum(w)
    return float(v[np.searchsorted(c, q / 100.0 * c[-1])])


def weighted_mean(samples) -> float:
    if not samples:
        return float("nan")
    v = np.array([s[0] for s in samples], dtype=float)
    w = np.array([s[1] for s in samples], dtype=float)
    return float(np.average(v, weights=w)) if w.sum() > 0 else float("nan")


def deadline_miss(samples, dropped: float, deadline: float) -> float:
    """Fraction of class-2 readings that failed to arrive on time.

    A DROPPED emergency message counts as a miss. For an ambulance the
    distinction between "arrived late" and "never arrived" is not worth
    drawing, and keeping them separate would let a defence look good on
    latency while quietly losing the message. Latency alone is reported
    separately as the p95 over delivered readings.
    """
    delivered = sum(w for _, w in samples)
    if delivered + dropped <= 0:
        return float("nan")
    late = sum(w for d, w in samples if d > deadline)
    return float((late + dropped) / (delivered + dropped))


def cluster_balance(counts):
    """1.0 when every cluster is the same size, falling as they diverge.

    Uses the coefficient of variation, so it is scale-free in cluster count.
    """
    counts = np.asarray(counts, dtype=float)
    if counts.size == 0 or counts.sum() == 0:
        return 0.0
    mu = counts.mean()
    if mu < 1e-12:
        return 0.0
    return float(1.0 / (1.0 + counts.std() / mu))
