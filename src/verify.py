"""Independent verification of the three claimed discrepancies.

Run:  python3 src/verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                       # noqa: E402
from network import Network                     # noqa: E402
from protocols.csgd_net import CSGDNet          # noqa: E402
from protocols.heed import HEED                 # noqa: E402
from protocols.leach import LEACH, LEACHC       # noqa: E402
from protocols.swarm import GACluster, PSOCluster  # noqa: E402

TABLE4 = {
    "LEACH":    [0.5, 0.35529, 0.22091, 0.12717, 0.039543],
    "LEACH-C":  [0.5, 0.37,    0.28339, 0.14785, 0.043871],
    "CSGD-NET": [0.5, 0.32982, 0.26095, 0.15064, 0.074354],
    "HEED":     [0.5, 0.41,    0.32,    0.23,    0.14],
    "PSO":      [0.5, 0.415,   0.33,    0.245,   0.16],
    "GA":       [0.5, 0.42,    0.34,    0.26,    0.18],
}
SAMPLE_ROUNDS = [1, 10, 20, 30, 40]


def rule(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------- TEST 1
def test_energy_budget():
    rule("TEST 1 - Energy budget per round, from the paper's own Eqs. (9)-(11)")
    cfg = Config()
    k = cfg.packet_bits

    e_elec_pkt = k * cfg.e_elec
    print(f"  k * Eelec                     = {e_elec_pkt*1e3:.4f} mJ  "
          f"(k={k} bit, Eelec={cfg.e_elec:.0e} J/bit)")
    print(f"  d0 = sqrt(eps_fs/eps_mp)      = {cfg.d0:.1f} m  -> free-space "
          f"term applies everywhere in a 50x50 m field")

    # Geometry: 100 nodes, 10 clusters, 50x50 m -> cluster area 250 m^2
    r_cluster = np.sqrt(250 / np.pi)
    d_mem = 2 * r_cluster / 3          # mean distance to centre of a disc
    d_ch = 50 / 3                      # mean node-to-centre distance in a square
    amp_mem = k * cfg.eps_fs * d_mem**2
    amp_ch = k * cfg.eps_fs * d_ch**2
    print(f"  mean member->CH distance      ~ {d_mem:.1f} m  -> amp "
          f"{amp_mem*1e3:.5f} mJ")
    print(f"  mean CH->RSU distance         ~ {d_ch:.1f} m  -> amp "
          f"{amp_ch*1e3:.5f} mJ")

    e_member = e_elec_pkt + amp_mem
    e_ch = 9 * e_elec_pkt + k * cfg.e_da * 10 + e_elec_pkt + amp_ch
    total = 90 * e_member + 10 * e_ch
    per_node = total / cfg.n_nodes
    print(f"\n  member cost/frame             = {e_member*1e3:.4f} mJ")
    print(f"  CH cost/frame (9 RX+agg+TX)   = {e_ch*1e3:.4f} mJ")
    print(f"  network/frame                 = {total*1e3:.2f} mJ  "
          f"-> {per_node*1e3:.4f} mJ per node")

    need = (0.5 - 0.039543) / 40
    print(f"\n  Table 4 LEACH needs             {need*1e3:.4f} mJ per node per round")
    print(f"  ratio                           {need/per_node:.1f}x")
    print(f"\n  => ONE frame per round is {need/per_node:.0f}x too cheap. But LEACH's")
    print("     steady-state phase is defined as MANY TDMA frames per round")
    print("     (Heinzelman 2000). The paper never states its frame count.")
    print(f"     {need/per_node:.0f} frames/round is an ordinary value.")


# ---------------------------------------------------------------- TEST 2
def _fitness_variants(net, ch, cfg, mode):
    """Every reading of Eq. 9 that the paper's text supports."""
    if ch.size == 0:
        return -np.inf
    e_net = net.energy[net.alive].sum()
    d_i = net.dist_to_rsu(ch)
    if mode == "A":      # literal: E = "overall residual energy of the network"
        return float(e_net / (cfg.initial_energy * max(d_i.sum(), 1e-9)))
    if mode == "B":      # per-CH ratios, network energy in numerator
        return float(np.sum(e_net / (cfg.initial_energy * np.maximum(d_i, 1e-9))))
    if mode == "C":      # set-level, CH energy in numerator  <-- what we shipped
        return float(net.energy[ch].sum() /
                     (cfg.initial_energy * max(d_i.sum(), 1e-9)))
    if mode == "D":      # per-CH, each CH's own energy
        return float(np.sum(net.energy[ch] /
                            (cfg.initial_energy * np.maximum(d_i, 1e-9))))
    raise ValueError(mode)


def test_fitness_readings():
    rule("TEST 2 - Eq. 9: which reading did we implement, and does it matter?")
    print("  Paper prose : 'targets the MINIMIZATION of ... the energy consumption")
    print("                 of CHs relative to overall network energy and the")
    print("                 distance separating the CHs from the RSU'")
    print("  Paper symbols: 'E represents the OVERALL RESIDUAL ENERGY within the")
    print("                 vehicular network, E0 is the initial energy'")
    print("  Printed form : f = E / (E0 * dis(CH_i, RSU))\n")

    cfg = Config(max_rounds=60)
    results = {}
    for mode in "ABCD":
        finals = []
        for seed in range(10):
            rng = np.random.default_rng(seed)
            net = Network(cfg, rng)
            proto = CSGDNet(cfg, np.random.default_rng(seed + 10_000))
            proto.fitness = lambda n, c, m=mode: _fitness_variants(n, c, cfg, m)
            fnd = None
            for r in range(cfg.max_rounds):
                if net.n_alive == 0:
                    break
                net.run_steady_state(proto.select_ch(net))
                if fnd is None and net.n_alive < cfg.n_nodes:
                    fnd = r + 1
            finals.append((net.residual_energy, fnd or cfg.max_rounds,
                           net.packets_to_rsu))
        results[mode] = np.mean(finals, axis=0)

    labels = {
        "A": "E=network residual, set-level  (literal reading)",
        "B": "E=network residual, per-CH sum (literal, per-CH)",
        "C": "E=sum of CH energies, set-level  <-- WE SHIPPED THIS",
        "D": "E=each CH's own energy, per-CH",
    }
    print(f"  {'mode':<6}{'residual@end':>14}{'FND':>8}{'packets':>10}   reading")
    for m in "ABCD":
        r = results[m]
        print(f"  {m:<6}{r[0]:>14.5f}{r[1]:>8.1f}{r[2]:>10.0f}   {labels[m]}")

    print("\n  Under readings A and B, E is the NETWORK's residual energy, which is")
    print("  identical for every candidate CH set within a round. It therefore")
    print("  cancels, and Eq. 9 collapses to a pure distance-to-RSU criterion:")
    print("  node energy plays NO role in CH selection at all.")


# ---------------------------------------------------------------- TEST 3
def test_linearity():
    rule("TEST 3 - Are Table 4's HEED/PSO/GA columns implausibly linear?")

    print("  Claim under test: successive differences are exactly equal, which")
    print("  real depletion traces are not.\n")
    print("  COUNTER-HYPOTHESIS: while all nodes are alive, per-round energy")
    print("  drain is near-constant, so residual energy IS near-linear. Rounding")
    print("  a near-linear trace to 2 dp can produce exactly equal differences.\n")

    n_seeds = 60
    cfg = Config(max_rounds=45)
    protos = {"LEACH": LEACH, "LEACH-C": LEACHC, "HEED": HEED,
              "CSGD-NET": CSGDNet}

    print(f"  Real traces from our simulator, sampled at rounds {SAMPLE_ROUNDS},")
    print(f"  then rounded to 2 dp (the precision the paper reports HEED/PSO/GA at):\n")
    print(f"  {'protocol':<10}{'std of diffs, full':>20}{'std, @2dp':>12}"
          f"{'exactly linear @2dp':>22}")
    for name, cls in protos.items():
        hits, stds_full, stds_2dp, n = 0, [], [], 0
        for seed in range(n_seeds):
            rng = np.random.default_rng(seed)
            net = Network(cfg, rng)
            proto = cls(cfg, np.random.default_rng(seed + 10_000))
            trace = []
            for r in range(cfg.max_rounds):
                if net.n_alive == 0:
                    break
                net.run_steady_state(proto.select_ch(net))
                trace.append(net.residual_energy)
            if len(trace) < 40:
                continue
            n += 1
            vals = np.array([trace[r - 1] for r in SAMPLE_ROUNDS])
            stds_full.append(np.diff(vals).std())
            d2 = np.diff(np.round(vals, 2))
            stds_2dp.append(d2.std())
            if np.allclose(d2, d2[0], atol=1e-12):
                hits += 1
        print(f"  {name:<10}{np.mean(stds_full):>20.4f}{np.mean(stds_2dp):>12.4f}"
              f"{f'{hits}/{n}':>22}")

    print("\n  Paper's own columns, std of successive differences:")
    for name, v in TABLE4.items():
        d = np.diff(v)
        mark = "  <- exactly linear" if d.std() < 1e-15 else ""
        print(f"    {name:<10}{d.std():>12.2e}{mark}")


if __name__ == "__main__":
    test_energy_budget()
    test_fitness_readings()
    test_linearity()
