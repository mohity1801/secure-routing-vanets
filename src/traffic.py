"""Traffic classes and priority assertion.

The base paper has one kind of traffic. Every node generates periodic telemetry,
every reading is aggregatable, and the only metric is energy. The words
"priority", "emergency" and "deadline" do not appear anywhere in it.

That is not an oversight to be argued for -- it is a structural conflict.
CSGD-NET's entire energy saving comes from a cluster head FUSING its members'
readings and forwarding one packet. Fusion means the head must wait for every
member's slot before it can send, so a reading's delay is the length of the
whole TDMA frame. An ambulance's message cannot wait for the frame, and it
cannot be averaged into a fused packet with 10 telemetry readings.

Two classes, therefore:

  class 0  telemetry   aggregatable, delay-tolerant. What the paper models.
  class 2  emergency   forwarded verbatim, deadline-bound.

(Class 1, a per-vehicle safety event, is deliberately not modelled yet. Two
classes are enough to show the mechanism and a third only adds parameters.)

A node's radio budget does not grow because its traffic is urgent: class-2
messages are a SUBSET of the `packets_per_round` readings a node already
generates, not extra ones. That keeps the energy accounting honest and means
`ems_frac = 0` reproduces the pre-priority results exactly.

WHO MAY ASSERT PRIORITY is the whole security question, and it is deferred to
`priority_auth` in Module 5b. Until then any node may claim class 2, which is
precisely the vulnerability: a cluster head receiving a class-2 assertion has
no way to tell an ambulance from a liar, so it must share the reserved capacity
between them.
"""

from __future__ import annotations

import numpy as np


class TrafficModel:
    """Which vehicles are emergency vehicles, and what each offers per round."""

    def __init__(self, cfg, rng, n_nodes: int, adversary=None):
        self.cfg = cfg
        self.n = n_nodes
        self.adversary = adversary

        n_ems = int(round(cfg.ems_frac * n_nodes))
        self.ems = (rng.choice(n_nodes, size=n_ems, replace=False)
                    if n_ems else np.array([], dtype=int))
        self.is_ems = np.zeros(n_nodes, dtype=bool)
        self.is_ems[self.ems] = True

        # An emergency vehicle is still an ordinary vehicle for every other
        # purpose -- it carries the same radio, spends the same energy, and can
        # be elected cluster head. Only its traffic differs.

        # Token bucket, so that even a genuine (or compromised) ambulance
        # cannot assert without limit. Charged in `demand` only.
        self.spent = np.zeros(n_nodes, dtype=float)
        self._window = -1
        # Per-node assertions this round, which is what a behavioural detector
        # at the RSU gets to see. Reset each round by `begin_round`.
        self.asserted = np.zeros(n_nodes, dtype=float)

    def begin_round(self, rnd: int) -> None:
        self.asserted[:] = 0.0
        if self.cfg.priority_budget > 0:
            w = rnd // max(self.cfg.priority_window, 1)
            if w != self._window:
                self._window = w
                self.spent[:] = 0.0

    # ---------------- demand ----------------
    def demand(self, nodes: np.ndarray, rnd: int) -> np.ndarray:
        """Class-2 messages each of `nodes` offers this round.

        Genuine EMS vehicles assert priority on a few of their readings.
        A false-priority attacker asserts on ALL of them -- there is no reason
        for it to hold back, and that asymmetry is what makes one attacker per
        cluster enough to exhaust the reservation (see attacks.py).
        """
        cfg = self.cfg
        nodes = np.asarray(nodes, dtype=int)
        if nodes.size == 0:
            return np.zeros(0, dtype=float)

        d = np.where(self.is_ems[nodes], float(cfg.ems_msgs_per_round), 0.0)

        adv = self.adversary
        if adv is not None:
            liar = np.array([adv.asserts_false_priority(int(i)) for i in nodes])
            # How greedy the liar is. At 1.0 it asserts on everything it sends,
            # which does the most damage and is the easiest to spot. Lowering it
            # toward the genuine EMS rate buys stealth at the cost of impact --
            # that trade-off is swept in run_priority.py --sweep-greed and is
            # the reason a behavioural detector BOUNDS this attack rather than
            # stopping it.
            d = np.where(liar, cfg.falsepriority_rate * cfg.packets_per_round, d)

        d = np.minimum(d, float(cfg.packets_per_round))

        if cfg.priority_budget > 0:
            allowance = np.maximum(cfg.priority_budget - self.spent[nodes], 0.0)
            d = np.minimum(d, allowance)
            self.spent[nodes] += d

        self.asserted[nodes] += d
        return d

    def demand_authorised(self, nodes: np.ndarray, rnd: int) -> np.ndarray:
        """The part of `demand` that comes from vehicles actually holding the
        emergency-vehicle role.

        A cluster head cannot compute this without authenticating the claim --
        that is the entire point. It is used two ways: to score how much of the
        reservation genuine ambulances actually got (always measurable by the
        simulator, never by the head), and, once `require_ems_auth` is on, as
        the demand the head is willing to admit at all.
        """
        nodes = np.asarray(nodes, dtype=int)
        if nodes.size == 0:
            return np.zeros(0, dtype=float)
        d = np.where(self.is_ems[nodes], float(self.cfg.ems_msgs_per_round), 0.0)
        return np.minimum(d, float(self.cfg.packets_per_round))

    def summary(self) -> str:
        return (f"{self.ems.size} EMS vehicles"
                if self.ems.size else "no EMS vehicles")
