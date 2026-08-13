"""Radio energy models. `cfg.radio_model` selects one; see docs/radio.md.

"heinzelman" (default) -- Eqs. (9)-(11) of the base paper:

    E_TX(k, d) = k*E_elec + k*eps_fs*d^2   if d <= d0
                 k*E_elec + k*eps_mp*d^4   if d >  d0
    E_RX(k)    = k*E_elec

This is the first-order model that LEACH, LEACH-C, HEED, PSO, GA and CSGD-NET
all share, so every protocol in the comparison is charged identically. It was
designed for short-range sensor motes: past d0 = 87.71 m the amplifier goes as
d^4, which at VANET distances (100-150 m) makes long links enormously
expensive and absolute lifetimes unrealistically short.

"logdistance" -- the robustness alternative. Log-distance path loss with a
single configurable exponent and NO knee: the transmit power needed to close a
link at distance d scales as d^gamma under log-distance path loss, so the
amplifier energy per bit is

    amp(d) = eps_ld * d^gamma,      eps_ld = eps_fs * d0^(2 - gamma)

CALIBRATION, stated explicitly: eps_ld is chosen so both models charge the
SAME amplifier energy at the reference distance d0 = sqrt(eps_fs/eps_mp) =
87.71 m -- the one distance where Heinzelman's own two branches agree. The two
models are therefore comparable rather than arbitrarily scaled, and every
difference between them is the tail behaviour (d^4 vs d^gamma beyond ~88 m,
d^2 vs d^gamma inside it), which is exactly the contested part of the model.
With gamma = 2 this reduces to the free-space branch extended over all
distances (eps_ld = eps_fs identically).

Exponents for 5.9 GHz DSRC, from the V2V measurement literature: ~1.8-2.1 for
highway LOS (we use 2.0), ~2.7-3.0 for urban streets with intersections and
building shadowing (we use 3.0, the harsh end of the bracket;
run_radio.py --experiment expsweep shows the conclusions are not sensitive to
the choice within it).

E_RX and aggregation are receiver/processing electronics, not propagation, so
they are identical under both models.
"""

from __future__ import annotations

import numpy as np


def tx_energy(cfg, k: int, d: float | np.ndarray):
    d = np.asarray(d, dtype=float)
    if cfg.radio_model == "heinzelman":
        amp = np.where(d <= cfg.d0, cfg.eps_fs * d**2, cfg.eps_mp * d**4)
    elif cfg.radio_model == "logdistance":
        amp = cfg.eps_ld * d ** cfg.path_loss_exp
    else:
        raise ValueError(f"unknown radio_model {cfg.radio_model!r}")
    return k * (cfg.e_elec + amp)


def rx_energy(cfg, k: int, n_signals: int = 1):
    return k * cfg.e_elec * n_signals


def aggregation_energy(cfg, k: int, n_signals: int):
    """Cost for a CH to fuse n_signals packets of k bits into one."""
    return k * cfg.e_da * n_signals
