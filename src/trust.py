"""CHIRP Module 2 -- Beta-reputation trust with credibility-weighted recommendations.

Three layers, each answering an attack the previous one cannot:

1. DIRECT trust. Members watchdog their head: did the aggregate reach the RSU?
   Evidence accumulates as Beta(alpha, beta) and trust is the posterior mean
   with Laplace smoothing, so an unobserved node starts at 0.5 rather than 0
   or 1. Catches blackhole and greyhole.

2. DECAY AND ASYMMETRIC PENALTY. Old evidence fades by `trust_decay` each
   round, and a failure counts `trust_penalty` times a success. Without the
   asymmetry an on-off attacker farms trust during quiet phases and spends it
   during active ones; with it, trust falls fast and recovers slowly.

3. CREDIBILITY-WEIGHTED RECOMMENDATIONS. The RSU fuses reports from many
   observers, weighting each by how far that observer's past reports have
   deviated from the consensus. A bad-mouther consistently reports honest
   heads as droppers and a ballot-stuffer consistently reports its colluders
   as perfect, so both accumulate deviation and lose weight. A plain average
   of recommendations has no such defence and is strictly worse -- which the
   `--no-credibility` ablation in run_module2.py measures.

Trust enters CH election in two places: as a fitness term (w_trust) and as a
hard eligibility gate (trust_gate), so a node the network believes is dropping
cannot be elected head at all.
"""

from __future__ import annotations

import numpy as np


class TrustEngine:
    def __init__(self, cfg, n_nodes: int, use_credibility: bool = True):
        self.cfg = cfg
        self.n = n_nodes
        self.use_credibility = use_credibility

        # Beta evidence held at the RSU, fused from member reports.
        self.alpha = np.zeros(n_nodes, dtype=float)
        self.beta = np.zeros(n_nodes, dtype=float)

        # Per-reporter credibility, tracked as mean absolute deviation of its
        # reports from the consensus for the same target in the same round.
        self.dev_sum = np.zeros(n_nodes, dtype=float)
        self.dev_count = np.zeros(n_nodes, dtype=float)

        self.first_flagged = np.full(n_nodes, -1, dtype=int)

    # ---------------- queries ----------------
    def score(self, idx=None) -> np.ndarray:
        """Posterior mean trust, Laplace-smoothed so unknown nodes sit at 0.5."""
        a, b = self.alpha, self.beta
        t = (a + 1.0) / (a + b + 2.0)
        return t if idx is None else t[np.asarray(idx)]

    def credibility(self, idx=None) -> np.ndarray:
        """1 for a reporter that always matches consensus, falling with deviation."""
        if not self.use_credibility:
            c = np.ones(self.n)
            return c if idx is None else c[np.asarray(idx)]
        mean_dev = self.dev_sum / np.maximum(self.dev_count, 1.0)
        c = 1.0 / (1.0 + self.cfg.cred_sharpness * mean_dev)
        c = np.where(self.dev_count > 0, c, 1.0)   # unproven reporters start neutral
        return c if idx is None else c[np.asarray(idx)]

    def trusted(self, idx=None) -> np.ndarray:
        return self.score(idx) >= self.cfg.trust_gate

    # ---------------- update ----------------
    def observe(self, net, outcome, adversary, rnd: int) -> None:
        """Fold one round of watchdog reports into the reputation state.

        `outcome` comes from Network.run_steady_state and carries, per cluster
        head, whether its aggregate actually reached the RSU.
        """
        cfg = self.cfg
        ch = outcome["ch"]
        if ch.size == 0:
            return

        # 1. Age existing evidence -- but only for nodes actually observed this
        # round. Decay shrinks alpha and beta together, so the posterior mean
        # drifts back toward the 0.5 prior; applying it to unobserved nodes
        # silently rehabilitates an attacker the moment the gate stops electing
        # it, which is precisely when it should stay excluded. Ageing evidence
        # per observation rather than per wall-clock round keeps a verdict
        # standing until new behaviour contradicts it.
        if cfg.decay_unobserved:
            self.alpha *= cfg.trust_decay
            self.beta *= cfg.trust_decay
        else:
            self.alpha[ch] *= cfg.trust_decay
            self.beta[ch] *= cfg.trust_decay
        members, slot = outcome["members"], outcome["slot"]
        forwarded = outcome["forwarded"]      # per-head delivered fraction
        if members is None or members.size == 0:
            return

        rng = net.rng
        # 2. each member observes its head, imperfectly
        seen = rng.random(members.size) < cfg.watchdog_p
        truth = forwarded[slot]
        noisy = np.where(rng.random(members.size) < cfg.watchdog_err,
                         1.0 - truth, truth)

        reporters = members[seen]
        targets = ch[slot[seen]]
        values = noisy[seen]

        if reporters.size == 0:
            return

        # 3. attackers substitute their own claims
        for i, (r, t) in enumerate(zip(reporters, targets)):
            if adversary is not None and adversary.falsifies_reports(int(r)):
                values[i] = adversary.falsify(int(r), int(t), float(values[i]))

        # 4. consensus per target, then per-reporter deviation from it
        cred = self.credibility(reporters)
        for target in np.unique(targets):
            m = targets == target
            v, w = values[m], cred[m]
            consensus = float(np.average(v, weights=w)) if w.sum() > 0 else float(v.mean())

            # credibility bookkeeping: how far did each reporter sit from it
            self.dev_sum[reporters[m]] += np.abs(v - consensus)
            self.dev_count[reporters[m]] += 1.0

            # 5. fuse into Beta evidence, weighted by reporter credibility.
            # A member sends packets_per_round packets to its head each round
            # and can watchdog every one of them, so a round yields that many
            # observations per member, not one. Counting one observation per
            # round starves the estimator: a greyhole is only elected head
            # every few rounds, so it would take tens of rounds to accumulate
            # enough evidence to cross the gate.
            wsum = float(w.sum()) if w.sum() > 0 else float(m.sum())
            wsum *= cfg.obs_per_round
            self.alpha[target] += consensus * wsum
            self.beta[target] += (1.0 - consensus) * wsum * cfg.trust_penalty

        # 6. record first time each node crossed below the gate
        low = (self.score() < cfg.trust_gate) & (self.first_flagged < 0)
        self.first_flagged[low] = rnd

    def observe_priority(self, net, rnd: int) -> None:
        """Fold priority-assertion rate into reputation (Module 5).

        This evidence is different in kind from the watchdog evidence above,
        and the difference is the point.

        Forwarding behaviour is PRIVATE: only a member that happened to be
        listening knows whether its head relayed the aggregate, observations
        are noisy, reporters lie, and the engine needs consensus and
        credibility weighting to recover the truth. Priority assertion is
        PUBLIC: it is stamped on the message, every head and the RSU sees it,
        and no watchdog or consensus is required to count it.

        So this needs no credibility layer. What it does need is a threshold,
        and the threshold is where the attack gets its room: a liar that
        asserts at the genuine EMS rate is behaviourally invisible here. It is
        also proportionally harmless, which is the honest form of the claim --
        a behavioural detector BOUNDS priority abuse, it does not stop it. Only
        an authenticated role attribute (`require_ems_auth`) stops it, and that
        is a cryptographic guarantee rather than a statistical one.
        """
        cfg = self.cfg
        traffic = getattr(net, "traffic", None)
        if traffic is None or cfg.packets_per_round <= 0:
            return

        rate = traffic.asserted / float(cfg.packets_per_round)
        over = rate > cfg.priority_flag_rate
        if not over.any():
            return

        # Weight the penalty by how far past the threshold the node went, so a
        # marginal over-asserter is not treated like a flat-out flooder.
        excess = np.clip(rate[over] - cfg.priority_flag_rate, 0.0, 1.0)
        self.beta[over] += excess * cfg.obs_per_round * cfg.priority_penalty

        low = (self.score() < cfg.trust_gate) & (self.first_flagged < 0)
        self.first_flagged[low] = rnd
