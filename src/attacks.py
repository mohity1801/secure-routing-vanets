"""Layer-A adversary model: attacks on routing and on the trust system itself.

See docs/threat_model.md. These are the attacks VeReMi does not contain,
because VeReMi never simulated routing -- packet dropping and reputation
manipulation only exist if the simulator has clusters and a trust engine.

The adversary is INTERNAL: every attacker holds a valid identity and is
indistinguishable from an honest node until it acts. That is the interesting
case, since Module 3's certificates already exclude outsiders.

Why CSGD-NET is defenceless here: Eq. 9 scores a candidate head on residual
energy and distance to the RSU. Both are self-reported and neither is a
behavioural observation, so an attacker that claims a full battery near an RSU
wins the head role every round and then drops whatever it likes.
"""

from __future__ import annotations

import numpy as np

BEHAVIOURS = ("blackhole", "greyhole", "badmouth", "ballot", "onoff",
              "falsepriority")


class Adversary:
    """Holds the attacker set and answers what each attacker does this round."""

    def __init__(self, cfg, rng, n_nodes: int):
        self.cfg = cfg
        self.rng = rng
        self.n = n_nodes

        n_att = int(round(cfg.attacker_frac * n_nodes))
        self.attackers = (rng.choice(n_nodes, size=n_att, replace=False)
                          if n_att else np.array([], dtype=int))
        self.is_attacker = np.zeros(n_nodes, dtype=bool)
        self.is_attacker[self.attackers] = True

        # Behaviour per attacker. A colluding set shares one behaviour mix so
        # ballot-stuffers know who their partners are.
        self.behaviour = np.empty(n_nodes, dtype=object)
        self.behaviour[:] = "honest"
        if n_att:
            kinds = cfg.attack_kinds or ["greyhole"]
            self.behaviour[self.attackers] = rng.choice(kinds, size=n_att)

        # On-off attackers alternate; phase offset per node so they are not
        # trivially synchronised.
        self.phase = rng.integers(0, max(cfg.onoff_period, 1), n_nodes)

    # ---------------- forwarding behaviour ----------------
    def drop_prob(self, node: int, rnd: int) -> float:
        """Probability this node drops a member reading while acting as head."""
        b = self.behaviour[node]
        if b == "blackhole":
            return 1.0
        if b == "greyhole":
            return self.cfg.greyhole_drop
        if b == "onoff":
            # "on" (malicious) for the first half of each period
            p = self.cfg.onoff_period
            return 1.0 if ((rnd + self.phase[node]) % p) < p // 2 else 0.0
        return 0.0

    def drop_probs(self, nodes: np.ndarray, rnd: int) -> np.ndarray:
        return np.array([self.drop_prob(int(i), rnd) for i in nodes], dtype=float)

    # ---------------- priority behaviour (Module 5) ----------------
    def asserts_false_priority(self, node: int) -> bool:
        """Claims emergency-vehicle status without holding the role.

        The attack this enables is not packet dropping -- a false-priority node
        forwards everything it is given. It attacks a RESOURCE. Emergency slots
        are reserved and finite, a cluster head with no way to authenticate the
        claim must share them proportionally, and this node asserts on every
        one of its readings while a real ambulance asserts on a handful. One
        attacker per cluster is therefore enough to take most of a reservation
        that was sized for ambulances.

        It is also the mirror image of the Module 2 energy finding. There, a
        dropper SAVED energy by skipping forwards it owed. Here the attacker
        spends nothing extra and IMPOSES cost on the honest head, which must
        forward each falsely-urgent message verbatim instead of fusing it. The
        free ride is externalised rather than banked, and what it buys is not
        battery -- it is an ambulance's deadline.
        """
        return self.behaviour[node] == "falsepriority"

    # ---------------- trust-report behaviour ----------------
    def falsifies_reports(self, node: int) -> bool:
        return self.behaviour[node] in ("badmouth", "ballot")

    def falsify(self, reporter: int, target: int, truth: float) -> float:
        """What `reporter` claims about `target` instead of the truth.

        badmouth: honest nodes are reported as droppers.
        ballot:   fellow attackers are reported as perfect forwarders.
        Both also protect their own kind, which is what makes a naive average
        of recommendations unusable.
        """
        b = self.behaviour[reporter]
        if b == "badmouth":
            return 0.0 if not self.is_attacker[target] else 1.0
        if b == "ballot":
            return 1.0 if self.is_attacker[target] else truth
        return truth

    def summary(self) -> str:
        if not self.attackers.size:
            return "no attackers"
        kinds, counts = np.unique(
            [self.behaviour[i] for i in self.attackers], return_counts=True)
        return ", ".join(f"{k}x{c}" for k, c in zip(kinds, counts))
