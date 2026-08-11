"""First-order radio energy model, Eqs. (9)-(11) of the base paper.

    E_TX(k, d) = k*E_elec + k*eps_fs*d^2   if d <= d0
                 k*E_elec + k*eps_mp*d^4   if d >  d0
    E_RX(k)    = k*E_elec

This is the Heinzelman model that LEACH, LEACH-C, HEED, PSO, GA and CSGD-NET
all share, so every protocol in the comparison is charged identically.
"""

from __future__ import annotations

import numpy as np


def tx_energy(cfg, k: int, d: float | np.ndarray):
    d = np.asarray(d, dtype=float)
    amp = np.where(d <= cfg.d0, cfg.eps_fs * d**2, cfg.eps_mp * d**4)
    return k * (cfg.e_elec + amp)


def rx_energy(cfg, k: int, n_signals: int = 1):
    return k * cfg.e_elec * n_signals


def aggregation_energy(cfg, k: int, n_signals: int):
    """Cost for a CH to fuse n_signals packets of k bits into one."""
    return k * cfg.e_da * n_signals
