"""CHIRP -- Module 1: mobility-aware, multi-metric cluster-head election.

The base paper's Eq. 9 scores a candidate CH set on two terms only:

    f = E / (E0 * dis(CH_i, RSU))

That has two consequences we measured in docs/reproducibility.md. Under the
paper's literal definition of E ("the overall residual energy within the
vehicular network") the energy term is constant within a round and cancels, so
selection reduces to distance-to-RSU. And there is no intra-cluster distance
term at all, so heads are pulled toward the RSU while their members transmit
from the edge.

CHIRP keeps the Cuckoo Search engine -- Levy flight, Gaussian walk, abandonment
-- byte-for-byte identical to CSGDNet and changes ONLY the objective. Any
difference in the results is therefore attributable to the objective, not to a
different optimiser. That is the point of subclassing rather than rewriting.

    f(S) = w_e*E + w_r*(1-D_rsu) + w_i*(1-D_intra) + w_l*LET + w_b*B + w_t*T

all six terms normalised to [0,1] and maximised:

  E      mean residual energy ratio of the heads
  D_rsu  mean head-to-nearest-RSU distance, normalised by tx_range
  D_intra mean member-to-head distance, normalised by tx_range   <- Eq. 9 lacks this
  LET    mean link expiration time between heads and their members  <- mobility
  B      cluster-size balance (coefficient of variation)
  T      mean trust of the heads -- stubbed at 1.0 until Module 2

Re-clustering is stability-triggered rather than every round: a fresh election
costs control traffic, and under mobility the useful question is not "has a
round elapsed" but "has the cluster stopped being valid".
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from energy import tx_energy                               # noqa: E402
from metrics import cluster_balance, link_expiration_time  # noqa: E402
from protocols.csgd_net import CSGDNet                     # noqa: E402


class CHIRP(CSGDNet):
    name = "CHIRP"
    association = "let"      # members join the longest-lived head, not the nearest

    def __init__(self, cfg, rng, trust=None):
        super().__init__(cfg, rng)
        # Module 2 will inject a real trust engine; until then every node is
        # fully trusted, which makes the trust term a no-op rather than a fudge.
        self.trust = trust
        self._ch = np.array([], dtype=int)
        self._last_election = -10**9
        self._last_ch_round = np.full(cfg.n_nodes, -10**9)

    def _pool(self, net) -> np.ndarray:
        """Eligible heads: alive, and not head again within the cooldown.

        Serving as head costs 88 mJ/round in the urban scenario against a 500
        mJ budget -- 7.6x an ordinary member -- while one re-election costs
        0.28 mJ. Rotation is 311x cheaper than the role it rotates, so the
        binding constraint on first-node-death is how often the same node is
        re-elected, not how often the network re-elects.
        """
        alive = np.where(net.alive)[0]

        # Module 2: hard trust gate. A node the network believes is dropping
        # cannot be elected head at all, independently of how attractive its
        # energy and position look. Falls back to the ungated pool if the gate
        # would leave too few candidates to form clusters.
        if self.trust is not None:
            ok = alive[self.trust.score(alive) >= self.cfg.trust_gate]
            if ok.size >= self.cfg.n_ch:
                alive = ok

        if self.cfg.ch_cooldown <= 0:
            return alive
        fresh = alive[net.round - self._last_ch_round[alive] >= self.cfg.ch_cooldown]
        # fall back to the full pool rather than starve the election
        return fresh if fresh.size >= self.cfg.n_ch else alive

    # ---------------- fitness ----------------
    def fitness(self, net, ch: np.ndarray) -> float:
        cfg = self.cfg
        if ch.size == 0:
            return -np.inf

        # --- energy: residual ratio of the heads.
        # First-node-death is set by the WEAKEST head, not the average one, so
        # rewarding the mean lets the optimiser hide a nearly-flat node inside
        # an otherwise healthy set.
        e_ratio = net.energy[ch] / cfg.initial_energy
        if cfg.energy_stat == "min":
            f_energy = float(e_ratio.min())
        elif cfg.energy_stat == "blend":
            f_energy = float(0.5 * e_ratio.mean() + 0.5 * e_ratio.min())
        else:
            f_energy = float(e_ratio.mean())

        # --- RSU reach cost.
        # Scored as ENERGY, not distance. The radio model has a knee at
        # d0 = sqrt(eps_fs/eps_mp) = 87.7 m, beyond which cost goes as d^4
        # rather than d^2. A head 150 m from an RSU is only 1.7x farther than
        # one at 88 m but costs ~9x as much to reach, and a distance-linear
        # term cannot see that. Scoring the actual transmit energy makes the
        # objective agree with the thing it is trying to conserve.
        e_ref = float(tx_energy(cfg, cfg.packet_bits, cfg.tx_range))
        e_rsu = float(tx_energy(cfg, cfg.packet_bits,
                                net.dist_to_rsu(ch)).mean())
        f_rsu = 1.0 - min(e_rsu / max(e_ref, 1e-30), 1.0)

        # --- membership: who would attach to these heads
        alive = np.where(net.alive)[0]
        members = alive[~np.isin(alive, ch)]
        if members.size == 0:
            return -np.inf

        # Score the set under the same association rule we will actually use,
        # otherwise the objective optimises a clustering we never build.
        m_in, slot_in, d_in, orphans = net.assign_members(ch, mode=self.association)
        if m_in.size == 0:
            return -np.inf
        in_range = np.ones(m_in.size, dtype=bool)
        d_min, slot = d_in, slot_in

        # --- intra-cluster compactness (the term Eq. 9 omits), also in energy
        e_intra = float(tx_energy(cfg, cfg.packet_bits, d_min).mean())
        f_intra = 1.0 - min(e_intra / max(e_ref, 1e-30), 1.0)

        # --- link stability: LET between each member and its chosen head
        h_in = ch[slot]
        let = link_expiration_time(
            net.pos[m_in], net.vel[m_in], net.pos[h_in], net.vel[h_in],
            cfg.tx_range,
        )
        # normalise against the re-clustering ceiling: any link that survives
        # longer than we would keep the cluster anyway is equally good
        horizon = cfg.recluster_max_rounds * cfg.round_duration
        f_let = float(np.clip(let / max(horizon, 1e-9), 0, 1).mean())

        # --- balance and coverage
        counts = np.bincount(slot, minlength=ch.size)
        f_bal = cluster_balance(counts)
        coverage = m_in.size / max(m_in.size + orphans.size, 1)

        # --- predicted survival of the WEAKEST head.
        #
        # Diagnosed, not guessed (src/diagnose_fnd.py): CHIRP's first casualty
        # is a cluster head 85% of the time, having served a 10.6-member
        # cluster. Receive energy scales linearly with cluster size, so the
        # better coverage this objective buys (4.2% orphans vs CSGD-NET's
        # 21.9%) lands as extra receive load on the heads -- 58.5 vs 46.6
        # mJ/round, which against E0=0.5 J predicts death at ~8.5 rounds and
        # measured 8.0. CSGD-NET is not cheaper, it just pushes the cost onto
        # orphans who pay their own direct-to-RSU transmission.
        #
        # None of the terms above see that: they score position and residual
        # energy, never what a head is about to spend. This one predicts each
        # head's actual round cost and rewards the minimum survival across the
        # set, because first-node-death is set by the weakest head.
        k = cfg.packet_bits
        e_rx = counts * k * cfg.e_elec
        e_agg = (counts + 1) * k * cfg.e_da
        e_fwd = tx_energy(cfg, k, net.dist_to_rsu(ch))
        cost = (e_rx + e_agg + e_fwd) * cfg.packets_per_round
        rounds_left = net.energy[ch] / np.maximum(cost, 1e-30)
        f_surv = float(np.clip(rounds_left.min() / cfg.survival_horizon, 0, 1))

        # --- trust (Module 2)
        f_trust = 1.0 if self.trust is None else float(self.trust.score(ch).mean())

        score = (cfg.w_energy * f_energy +
                 cfg.w_rsu * f_rsu +
                 cfg.w_intra * f_intra +
                 cfg.w_let * f_let +
                 cfg.w_balance * f_bal +
                 cfg.w_survival * f_surv +
                 cfg.w_trust * f_trust)

        # An election that strands members helps nobody; scale by coverage so
        # orphaning is penalised smoothly rather than by a hard constraint.
        return float(score * coverage)

    # ---------------- stability-triggered re-election ----------------
    def needs_reelection(self, net) -> bool:
        cfg = self.cfg
        live_ch = np.array([c for c in self._ch if net.alive[c]], dtype=int)
        if live_ch.size == 0:
            return True
        if live_ch.size < self._ch.size:            # a head died
            return True
        if net.round - self._last_election >= cfg.recluster_max_rounds:
            return True

        # a head has fallen well below the network's mean energy
        mean_e = net.energy[net.alive].mean()
        if (net.energy[live_ch] < cfg.recluster_energy_frac * mean_e).any():
            return True

        # too many member links are about to expire
        members, slot, _, _ = net.assign_members(live_ch, mode=self.association)
        if members.size == 0:
            return True
        heads = live_ch[slot]
        let = link_expiration_time(
            net.pos[members], net.vel[members], net.pos[heads], net.vel[heads],
            cfg.tx_range,
        )
        expiring = float((let < cfg.recluster_let_thresh).mean())
        return expiring > cfg.recluster_let_frac

    def select_ch(self, net) -> np.ndarray:
        self.reelected = self.needs_reelection(net)
        if self.reelected:
            self._ch = super().select_ch(net)
            self._last_election = net.round
        else:
            self._ch = np.array([c for c in self._ch if net.alive[c]], dtype=int)
        self._last_ch_round[self._ch] = net.round
        return self._ch
