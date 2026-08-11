"""Simulation parameters.

Baseline values are taken from Table 3 of the base paper (Sellami, Mchergui,
Alaya, "Optimizing vehicular networks communications through green clustering
and data aggregation", Cluster Computing 29:16, 2026).

NOTE ON UNITS: Table 3 lists Eelec=50, eps_fs=10, eps_mp=0.0013 without units.
These are exactly the conventional Heinzelman values (50 nJ/bit, 10 pJ/bit/m^2,
0.0013 pJ/bit/m^4), so the omission is cosmetic and we adopt them.

NOTE ON FRAMES PER ROUND: a single member->CH->RSU exchange costs ~0.64 mJ per
node, which alone cannot take a node from 0.5 J to 0.04 J in 40 rounds. That is
NOT a defect in the paper: LEACH's steady-state phase is defined as many TDMA
frames per round (Heinzelman 2000), and the paper simply never states its frame
count. Fitting that one free parameter against Table 4's LEACH column gives 22
frames/round with RMSE 0.008 -- i.e. the paper IS reproducible without altering
any equation. See docs/reproducibility.md finding 1 and src/verify_fit.py.

NOTE ON INITIAL ENERGY: Table 3 renders it as "1.01 d", which is not a readable
quantity. Table 4 starts every protocol at 0.5, so we use 0.5 J.
"""

from dataclasses import dataclass, field


@dataclass
class Config:
    # --- Network (Table 3) ---
    n_nodes: int = 100
    area_x: float = 50.0
    area_y: float = 50.0
    rsu_pos: tuple = (25.0, 25.0)   # Sect. 4.2: "base station placed at the center"
    initial_energy: float = 0.5     # J, per Table 4
    packet_bits: int = 6400

    # --- Radio model (Eqs. 9-11) ---
    e_elec: float = 50e-9           # J/bit
    eps_fs: float = 10e-12          # J/bit/m^2
    eps_mp: float = 0.0013e-12      # J/bit/m^4
    e_da: float = 5e-9              # J/bit/signal, aggregation cost (not stated
                                    # in the paper; standard LEACH value)

    # --- TDMA frames per round; fitted to Table 4's LEACH column ---
    packets_per_round: int = 22

    # --- Cluster setup-phase control packet (ADV / JOIN / schedule).
    # The base paper charges nothing for re-clustering, which makes electing
    # every round look free. Module 1 charges it. ~25 bytes.
    ctrl_bits: int = 200

    # --- Which reading of Eq. 9 to use; see docs/reproducibility.md finding 2 ---
    #   "A" literal    : E = network residual energy (cancels -> distance-only)
    #   "C" charitable : E = summed residual energy of the candidate CH set
    fitness_mode: str = "C"

    # --- Clustering ---
    ch_percent: float = 0.10        # Table 3: "CHs percentage 10"

    # --- Cuckoo Search (Table 3) ---
    n_cuckoos: int = 10
    max_iterations: int = 20
    pa: float = 0.25                # discovery probability, Yang & Deb default
    levy_beta: float = 1.5
    levy_alpha: float = 0.01
    gauss_sigma: float = 0.05       # fraction of area, for the Gaussian walk

    # --- Run control ---
    max_rounds: int = 200
    seed: int = 0

    # ================= Module 1: mobility =================
    scenario: str = "static"        # "static" | "highway" | "urban"
    round_duration: float = 1.0     # seconds of movement per round
    tx_range: float = 100.0         # m, DSRC-like; also R in the LET formula
    n_rsus: int = 1                 # RSUs are spread evenly over the road
    rsu_layout: str = "auto"        # "auto" | "line" (road) | "grid" (2D area)

    # highway
    n_lanes: int = 6                # half each direction
    # urban
    block: float = 200.0            # m between parallel roads
    p_turn: float = 0.35            # turn probability at an intersection

    speed_mean: float = 25.0        # m/s
    speed_std: float = 4.0
    speed_min: float = 8.0
    speed_max: float = 33.0

    # ========= Module 1: CHIRP multi-metric fitness =========
    # Weights over: energy, RSU reach cost, intra-cluster compactness,
    # link stability (LET), cluster balance, trust. Sum to 1.
    #
    # Set from the ablation in docs/module1.md, not by hand: dropping the
    # energy term costs 37% of first-node-death and dropping intra costs 2.2%
    # of energy per reading, while LET, RSU and balance each moved results by
    # under 1%. Weight moved from LET (0.25 -> 0.05) into energy and intra.
    w_energy: float = 0.30
    w_rsu: float = 0.10
    w_intra: float = 0.35
    w_let: float = 0.05
    w_balance: float = 0.10
    w_trust: float = 0.10

    # w_survival predicts each head's round cost (receive + aggregate + forward)
    # and rewards the weakest head's remaining rounds. SECOND NEGATIVE RESULT,
    # default off: it made urban FND monotonically worse (8.5 -> 7.0 as the
    # weight went 0 -> 0.65) because orphans do not count toward a head's cost,
    # so the optimiser raised the minimum survival by orphaning members --
    # orphan rate climbed 3.9% -> 6.0% in the same sweep. Kept for the report.
    w_survival: float = 0.00
    survival_horizon: float = 15.0  # rounds; normalises the survival term

    # Rounds a node must sit out before it can be head again. Serving as head
    # costs ~7.6x an ordinary member (88 vs 11.6 mJ/round in urban) while one
    # re-election costs 0.28 mJ -- 311x cheaper than the role it rotates. So
    # first-node-death is governed by how often the SAME node is re-elected.
    # Swept 0..7: highway FND 21.9 -> 24.0, urban 9.2 -> 10.2, both plateauing
    # around 3-5 while last-node-death slowly falls. See docs/module1.md.
    ch_cooldown: int = 3

    # Member association: 0 = nearest head, 1 = longest-lived link.
    # NEGATIVE RESULT, kept deliberately: sweeping this on the highway is
    # monotonically worse as it rises (FND 16.1->14.1, mJ/reading 0.728->0.792,
    # intra 28.3->37.7 m) while re-clustering barely moves (0.78->0.79). At
    # 1 node/10 m there is always a near same-direction candidate, so biasing
    # toward link lifetime only buys distance. Default off. See docs/module1.md.
    assoc_let_weight: float = 0.0

    # Which statistic of CH residual energy the fitness rewards.
    # "min" protects the weakest head, which is what first-node-death measures.
    energy_stat: str = "mean"       # "mean" | "min" | "blend"

    # Stability-triggered re-clustering. THIRD NEGATIVE RESULT: holding heads
    # across rounds saves setup traffic but concentrates the head role, and the
    # head role costs 311x what a re-election costs. Raising the ceiling from 1
    # to 5 cost 26% of urban FND (10.1 -> 7.8) and 35% of highway FND
    # (23.3 -> 17.2) to save a negligible amount of control energy. Default 1,
    # i.e. re-elect every round; the mechanism is kept because fewer elections
    # may still matter for Module 2 (fewer chances for a malicious node to win
    # the head role), which is a security question, not an energy one.
    recluster_max_rounds: int = 1   # hard ceiling between re-elections
    recluster_let_frac: float = 0.4  # re-elect if this fraction of members
    recluster_let_thresh: float = 2.0  # have LET below this many seconds
    recluster_energy_frac: float = 0.5  # or a CH drops below this x mean energy

    # ================= Module 2: adversary =================
    attacker_frac: float = 0.0
    attack_kinds: tuple = ("greyhole",)
    greyhole_drop: float = 0.5      # fraction a greyhole silently discards
    onoff_period: int = 8           # rounds; malicious for the first half

    # ================= Module 2: trust engine =================
    watchdog_p: float = 0.85        # chance a member observes its head at all
    watchdog_err: float = 0.05      # chance an observation is simply wrong
    obs_per_round: int = 22         # watchdog observations per member per round
                                    # (one per TDMA frame; = packets_per_round)
    trust_decay: float = 0.90       # ageing of Beta evidence, per OBSERVATION
    decay_unobserved: bool = False  # True rehabilitates nodes the gate excludes
    trust_penalty: float = 3.0      # a failure counts this many successes
    trust_gate: float = 0.40        # below this a node cannot be elected head
    cred_sharpness: float = 4.0     # how fast credibility falls with deviation
    trust_warmup: int = 8           # rounds before 'late' attacker-CH share counts
    eval_alive_frac: float = 0.5    # stop evaluating at half-node-death

    # ============ Module 5: priority / emergency traffic ============
    # The base paper models one traffic class. See src/traffic.py for why a
    # second one is a structural conflict with aggregation rather than a
    # missing feature. ems_frac = 0 reproduces every pre-Module-5 result.
    ems_frac: float = 0.0           # fraction of vehicles that are EMS
    ems_msgs_per_round: int = 4     # class-2 messages an EMS vehicle offers

    # Reserved class-2 slots per cluster per FRAME. Capacity per round is
    # therefore emergency_slots * packets_per_round. A false-priority attacker
    # asserts on all packets_per_round of its readings, so at the default of 1
    # a single attacker in a cluster exactly saturates the reservation.
    emergency_slots: int = 1

    # A class-2 message served from the reservation skips the fusion wait; one
    # that does not fit falls back to ordinary aggregated service.
    deadline_slots: float = 4.0     # class-2 deadline, in TDMA slots

    # Per-message authentication overhead. Emergency traffic bypasses fusion so
    # it cannot be covered by the aggregate MAC and needs its own signature.
    # Both default to 0 so Module 3b can fill in measured values later without
    # invalidating anything measured now. See docs/priority.md.
    sig_bits: int = 0               # per class-2 message
    mac_bits: int = 0               # on the fused class-0 packet

    # Module 5b: only role-bearing (EMS) vehicles may assert class 2. Off by
    # default so the undefended case is the baseline.
    require_ems_auth: bool = False
    # Refuse reserved slots to nodes the trust engine distrusts. Without this,
    # detecting a false-priority attacker changes nothing: the trust gate only
    # blocks CH ELECTION, and asserting priority does not require being a head.
    priority_trust_gate: bool = False
    priority_budget: int = 0        # 0 = unlimited; else assertions per window
    priority_window: int = 5        # rounds

    # How greedily a false-priority attacker asserts, as a fraction of its own
    # readings. 1.0 is maximally greedy and maximally visible; dropping toward
    # ems_msgs_per_round/packets_per_round (= 0.18 at the defaults) makes it
    # indistinguishable from a genuine ambulance but proportionally harmless.
    falsepriority_rate: float = 1.0
    # Behavioural detector: assertion rate above which the RSU treats a node as
    # abusing priority. Sits between the genuine rate and a greedy liar's.
    priority_flag_rate: float = 0.5
    priority_penalty: float = 2.0   # Beta evidence weight for an over-asserter

    @property
    def d0(self) -> float:
        """Free-space / multipath crossover distance."""
        return (self.eps_fs / self.eps_mp) ** 0.5

    @property
    def n_ch(self) -> int:
        return max(1, int(round(self.ch_percent * self.n_nodes)))


PAPER = Config()
