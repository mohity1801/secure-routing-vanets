"""Network state: node positions and velocities, energy bookkeeping, and one
round of the steady-state (TDMA) phase shared by every clustered protocol.

Module 1 adds mobility and multiple RSUs. With `scenario="static"` and
`n_rsus=1` the behaviour is identical to the base paper's model, so the
reproduction in run_baseline.py is unaffected.
"""

from __future__ import annotations

import numpy as np

import mobility as mobility_mod
from energy import aggregation_energy, rx_energy, tx_energy


class Network:
    def __init__(self, cfg, rng: np.random.Generator):
        self.cfg = cfg
        self.rng = rng
        self.mobility = mobility_mod.build(cfg, rng)
        self.pos, self.vel = self.mobility.initial_state(cfg.n_nodes)
        self.energy = np.full(cfg.n_nodes, cfg.initial_energy, dtype=float)
        self.rsus = self._place_rsus()

        self.packets_to_rsu = 0
        self.packets_offered = 0
        self.readings_generated = 0.0   # PDR numerator/denominator
        self.readings_delivered = 0.0
        self.round = 0

        # Module 5: traffic classes. Attached by the runner (like
        # association_mode) rather than built here, so Network never draws from
        # self.rng for it -- that would shift every mobility trace.
        self.traffic = None
        self.trust = None       # set by the runner when trust gates priority
        self.readings_generated_emerg = 0.0
        self.readings_delivered_emerg = 0.0

        # Weighted delay samples: (slots, n_readings_delivered). Kept per
        # cluster per round rather than per reading -- ~10 entries a round
        # instead of ~2000, and the weighting makes the percentiles identical.
        self.delay_norm: list[tuple[float, float]] = []
        self.delay_emerg: list[tuple[float, float]] = []
        # class-2 readings generated but never delivered; a dropped emergency
        # message misses its deadline just as surely as a late one
        self.emerg_dropped = 0.0

        # The same, restricted to vehicles that actually hold the EMS role.
        # This is the safety metric: what a real ambulance experienced, as
        # opposed to what everything claiming to be one did.
        self.readings_generated_emerg_gen = 0.0
        self.readings_delivered_emerg_gen = 0.0
        self.delay_emerg_gen: list[tuple[float, float]] = []
        self.emerg_gen_dropped = 0.0

        # Energy heads spent forwarding class-2 messages verbatim, and how much
        # of it served demand from vehicles with no right to assert priority.
        # This is what the attack costs its victims rather than what it costs
        # the attacker -- the Module 2 free ride, externalised.
        self.priority_energy = 0.0
        self.priority_energy_false = 0.0

        # per-round cluster-quality trace (Module 1)
        self.orphan_rate: list[float] = []
        self.intra_dist: list[float] = []
        self.n_clusters: list[int] = []

    def _place_rsus(self) -> np.ndarray:
        """Line layout along a road, grid layout over a 2D area.

        Placing RSUs in a line down the middle of a 600x600 m grid leaves the
        corners over 300 m from the nearest one. Past d0 = 87.7 m the radio
        model charges d^4, so those nodes drain in a single round -- which is
        exactly what made every urban run report FND = 1.
        """
        cfg = self.cfg
        if cfg.n_rsus <= 1:
            return np.array([cfg.rsu_pos], dtype=float)

        layout = cfg.rsu_layout
        if layout == "auto":
            layout = "grid" if cfg.area_y / cfg.area_x > 0.3 else "line"

        if layout == "line":
            xs = (np.arange(cfg.n_rsus) + 0.5) * cfg.area_x / cfg.n_rsus
            ys = np.full(cfg.n_rsus, cfg.area_y / 2)
            return np.column_stack([xs, ys])

        side = int(np.ceil(np.sqrt(cfg.n_rsus)))
        gx = (np.arange(side) + 0.5) * cfg.area_x / side
        gy = (np.arange(side) + 0.5) * cfg.area_y / side
        pts = np.array([(x, y) for y in gy for x in gx])[:cfg.n_rsus]
        return pts.astype(float)

    # --- state queries -------------------------------------------------
    @property
    def alive(self) -> np.ndarray:
        return self.energy > 0

    @property
    def n_alive(self) -> int:
        return int(self.alive.sum())

    @property
    def residual_energy(self) -> float:
        """Mean residual energy per node -- the quantity plotted in Table 4."""
        return float(np.clip(self.energy, 0, None).mean())

    def dist_to_rsu(self, idx=None) -> np.ndarray:
        """Distance to the NEAREST RSU."""
        p = self.pos if idx is None else self.pos[idx]
        p = np.atleast_2d(p)
        d = np.linalg.norm(p[:, None, :] - self.rsus[None, :, :], axis=2)
        return d.min(axis=1)

    def dist(self, i, j) -> np.ndarray:
        return np.linalg.norm(self.pos[i] - self.pos[j], axis=-1)

    def step_mobility(self) -> None:
        self.pos, self.vel = self.mobility.step(
            self.pos, self.vel, self.cfg.round_duration
        )

    # --- steady-state phase --------------------------------------------
    def assign_members(self, ch_idx: np.ndarray, mode: str | None = None):
        """Attach each alive non-CH node to an in-range CH.

        mode "nearest": closest head, which is what every baseline does.
        mode "let":     among in-range heads, the one whose link survives
                        longest (Su & Zhang LET), distance as the tie-break.

        Nearest-head association is what breaks clustering under mobility: on a
        bidirectional road the closest head is often in the opposing lane,
        closing at up to 2x the speed limit, so the link dies within a round.
        Choosing by link lifetime instead keeps members with traffic going
        their own way.

        Returns (members, slot, d_member, orphans). Nodes with no CH within
        tx_range are orphans and report straight to the RSU, which is the
        paper's isolated-vehicle rule (Sect. 3.3.2).
        """
        mode = mode or getattr(self, "association_mode", "nearest")
        alive = np.where(self.alive)[0]
        members = alive[~np.isin(alive, ch_idx)]
        if ch_idx.size == 0 or members.size == 0:
            return members, None, None, members

        d = np.linalg.norm(self.pos[members][:, None, :] -
                           self.pos[ch_idx][None, :, :], axis=2)
        reachable = d <= self.cfg.tx_range
        has_ch = reachable.any(axis=1)

        if mode == "let":
            from metrics import link_expiration_time
            let = link_expiration_time(
                self.pos[members][:, None, :], self.vel[members][:, None, :],
                self.pos[ch_idx][None, :, :], self.vel[ch_idx][None, :, :],
                self.cfg.tx_range,
            )
            # Blend link lifetime against reach cost. Pure-LET association is a
            # bad trade: it attaches members to distant heads travelling the
            # same way, and the extra amplifier energy outweighs the stability
            # gained. alpha is swept in run_module1.py --sweep-assoc.
            a = self.cfg.assoc_let_weight
            horizon = self.cfg.recluster_max_rounds * self.cfg.round_duration
            f_let = np.clip(let / max(horizon, 1e-9), 0, 1)
            f_near = 1.0 - np.clip(d / self.cfg.tx_range, 0, 1)
            score = np.where(reachable, a * f_let + (1 - a) * f_near, -np.inf)
            slot = score.argmax(axis=1)
        else:
            slot = np.where(reachable, d, np.inf).argmin(axis=1)

        d_member = d[np.arange(members.size), slot]
        orphans = members[~has_ch]
        return members[has_ch], slot[has_ch], d_member[has_ch], orphans

    def run_setup_phase(self, ch_idx: np.ndarray) -> None:
        """Charge the cluster setup phase: CH advertisement, member join, and
        the TDMA schedule broadcast.

        The base paper's energy model covers only the steady-state phase, so
        re-electing every round appears free. It is not: every election floods
        an ADV from each head and a JOIN from each member. Charging it is what
        makes CHIRP's stability-triggered re-clustering measurable.
        """
        cfg = self.cfg
        kc = cfg.ctrl_bits
        ch_idx = np.asarray([c for c in ch_idx if self.alive[c]], dtype=int)
        if ch_idx.size == 0:
            return

        # 1. each head broadcasts an advertisement across the full radio range
        self.energy[ch_idx] -= float(tx_energy(cfg, kc, cfg.tx_range))

        members, slot, d_member, _ = self.assign_members(ch_idx)
        if members.size:
            # 2. members hear every advertisement, then send one join request
            self.energy[members] -= rx_energy(cfg, kc, ch_idx.size)
            self.energy[members] -= tx_energy(cfg, kc, d_member)
            # 3. heads receive the joins and broadcast the TDMA schedule
            counts = np.bincount(slot, minlength=ch_idx.size)
            for s, ch in enumerate(ch_idx):
                self.energy[ch] -= rx_energy(cfg, kc, int(counts[s]))
            self.energy[ch_idx] -= float(tx_energy(cfg, kc, cfg.tx_range))

        self._reap()

    def run_steady_state(self, ch_idx: np.ndarray, adversary=None) -> dict:
        """Charge one round of TDMA data transfer given the elected CHs.

        With an adversary, a head forwards only a fraction of what it received.
        A dropping head still pays to RECEIVE its members' data -- it cannot
        avoid that without revealing itself by leaving the TDMA schedule -- but
        it skips the forward transmit in proportion to what it drops, so
        attacking is energetically cheaper than behaving. That asymmetry is
        real and it matters: it means an attacker also wins the energy metric,
        so a defence cannot be validated on energy alone.

        Returns the per-round record the trust engine consumes.
        """
        cfg = self.cfg
        k = cfg.packet_bits
        f = cfg.packets_per_round
        ch_idx = np.asarray([c for c in ch_idx if self.alive[c]], dtype=int)

        members, slot, d_member, orphans = self.assign_members(ch_idx)
        self.packets_offered += (members.size + orphans.size + ch_idx.size) * f

        total_non_ch = members.size + orphans.size
        self.orphan_rate.append(orphans.size / max(total_non_ch, 1))
        self.intra_dist.append(float(d_member.mean()) if members.size else 0.0)
        self.n_clusters.append(int(ch_idx.size))

        # Members -> their CH
        if members.size:
            self.energy[members] -= tx_energy(cfg, k, d_member) * f

        # Orphans -> straight to the RSU
        if orphans.size:
            self.energy[orphans] -= tx_energy(cfg, k, self.dist_to_rsu(orphans)) * f
            self.packets_to_rsu += orphans.size * f

        # CHs: receive + aggregate + forward one fused packet to the nearest RSU
        forwarded = np.ones(ch_idx.size, dtype=float)
        if ch_idx.size:
            counts = (np.bincount(slot, minlength=ch_idx.size)
                      if slot is not None else np.zeros(ch_idx.size, int))
            d_rsu = self.dist_to_rsu(ch_idx)
            if adversary is not None:
                forwarded = 1.0 - adversary.drop_probs(ch_idx, self.round)

            for s, ch in enumerate(ch_idx):
                n_sig = int(counts[s])
                cost = rx_energy(cfg, k, n_sig) + aggregation_energy(cfg, k, n_sig + 1)
                # a dropper skips the forward in proportion to what it drops
                cost += float(tx_energy(cfg, k, float(d_rsu[s]))) * forwarded[s]
                self.energy[ch] -= cost * f
            self.packets_to_rsu += int(forwarded.sum() * f)

            # readings that actually reached the RSU this round
            self.readings_delivered += float((counts * forwarded).sum() * f)
            self.readings_delivered += float(forwarded.sum() * f)   # heads' own
        self.readings_delivered += orphans.size * f                 # direct path
        self.readings_generated += (members.size + orphans.size + ch_idx.size) * f

        self._priority_phase(ch_idx, counts if ch_idx.size else None, slot,
                             forwarded, d_rsu if ch_idx.size else None,
                             members, orphans, f)

        self._reap()
        self.round += 1
        return {"ch": ch_idx, "members": members, "slot": slot,
                "forwarded": forwarded, "orphans": orphans}

    def _priority_phase(self, ch_idx, counts, slot, forwarded, d_rsu,
                        members, orphans, f):
        """Class-2 arbitration: reservation, aggregation bypass, delay.

        DELAY IS MEASURED IN TDMA SLOTS, never milliseconds. This simulator has
        no channel and no time below the round, so a millisecond figure would
        be invented. A TDMA schedule, though, is a real finite resource in the
        base paper's own model and the delay it imposes is exactly computable:

            aggregated  = counts + 1   member slots, then the head's forward
            bypassed    = 2            reserved slot, then an immediate forward
            orphan      = 1            direct to the RSU, nothing to wait for

        Aggregation is what couples delay to cluster size: the head cannot send
        until every member's slot has passed, because it is fusing them all into
        one packet, so every reading waits for the whole frame regardless of its
        own position in it. Bypassing fusion is what decouples them -- and it
        costs exactly the energy that fusing was saving.

        THE RESERVATION IS FINITE. `emergency_slots` slots per frame gives
        `emergency_slots * packets_per_round` class-2 messages per cluster per
        round. Demand above that falls back to ordinary aggregated service.

        THE HEAD CANNOT TELL AN AMBULANCE FROM A LIAR. Without
        `require_ems_auth` every class-2 claim is admitted, so an oversubscribed
        reservation is shared PROPORTIONALLY between genuine and false demand --
        a false-priority attacker does not merely add load, it takes a share of
        a resource an ambulance needed. With authorisation on, only role-bearing
        demand is admitted and the liar's share drops to zero.
        """
        if self.traffic is None:
            return
        cfg = self.cfg
        k = cfg.packet_bits

        e_orp = self.traffic.demand(orphans, self.round)
        g_orp = self.traffic.demand_authorised(orphans, self.round)
        e_mem = self.traffic.demand(members, self.round)
        g_mem = self.traffic.demand_authorised(members, self.round)
        e_ch = self.traffic.demand(ch_idx, self.round)
        g_ch = self.traffic.demand_authorised(ch_idx, self.round)

        self.readings_generated_emerg += float(e_mem.sum() + e_orp.sum()
                                               + e_ch.sum())
        self.readings_generated_emerg_gen += float(g_mem.sum() + g_orp.sum()
                                                   + g_ch.sum())

        # Orphans bypass the cluster entirely, so they are already the fast
        # path and need no reservation.
        if orphans.size:
            eo, go = float(e_orp.sum()), float(g_orp.sum())
            no = max(orphans.size * f - eo, 0.0)
            if no > 0:
                self.delay_norm.append((1.0, no))
            if eo > 0:
                self.delay_emerg.append((1.0, eo))
                self.readings_delivered_emerg += eo
            if go > 0:
                self.delay_emerg_gen.append((1.0, go))
                self.readings_delivered_emerg_gen += go

        if ch_idx.size == 0 or counts is None:
            return

        by_cluster = (lambda v: np.bincount(slot, weights=v,
                                            minlength=ch_idx.size)
                      if slot is not None and v.size
                      else np.zeros(ch_idx.size))
        demand = by_cluster(e_mem) + e_ch
        genuine = by_cluster(g_mem) + g_ch

        # WHAT THE HEAD IS WILLING TO ADMIT. Three regimes, and the difference
        # between them is the whole experiment.
        #
        #   default          every claim admitted -- the head has no way to
        #                    check one, so genuine and false demand share the
        #                    reservation in proportion
        #   priority_trust_gate  claims from nodes the network distrusts are
        #                    refused. Statistical, so it inherits the trust
        #                    engine's false positives: an ambulance wrongly
        #                    distrusted loses its slot, and that shows up here
        #                    rather than being assumed away
        #   require_ems_auth an authenticated role attribute settles it. Not a
        #                    statistical judgement at all
        if cfg.require_ems_auth:
            adm_mem, adm_ch = g_mem, g_ch
        else:
            adm_mem, adm_ch = e_mem, e_ch
            if self.trust is not None and cfg.priority_trust_gate:
                adm_mem = np.where(self.trust.trusted(members), adm_mem, 0.0)
                adm_ch = np.where(self.trust.trusted(ch_idx), adm_ch, 0.0)
        adm_gen_mem = np.minimum(adm_mem, g_mem)
        adm_gen_ch = np.minimum(adm_ch, g_ch)

        admitted = by_cluster(adm_mem) + adm_ch
        admitted_gen = by_cluster(adm_gen_mem) + adm_gen_ch

        capacity = float(cfg.emergency_slots * f)
        served = np.minimum(admitted, capacity)
        with np.errstate(invalid="ignore", divide="ignore"):
            share = np.where(admitted > 0, served / np.maximum(admitted, 1e-12), 0.0)
        served_gen = admitted_gen * share

        total = (counts + 1.0) * f
        normal = np.maximum(total - demand, 0.0)
        agg_delay = counts + 1.0

        for s, ch in enumerate(ch_idx):
            fw = float(forwarded[s])
            byp = float(served[s])

            # --- delay
            if normal[s] > 0:
                self.delay_norm.append((float(agg_delay[s]), float(normal[s] * fw)))
            self._log_emerg(self.delay_emerg, float(agg_delay[s]),
                            byp, float(demand[s]), fw, gen=False)
            self._log_emerg(self.delay_emerg_gen, float(agg_delay[s]),
                            float(served_gen[s]), float(genuine[s]), fw, gen=True)

            if byp <= 0:
                continue

            # --- energy. Bypassed readings are no longer fused, so refund the
            # aggregation the loop above already charged for them, then pay to
            # forward each one individually with its own signature. This is the
            # price of priority, and it is charged to the head.
            self.energy[ch] += float(aggregation_energy(cfg, k, byp))
            fwd_cost = float(
                tx_energy(cfg, k + cfg.sig_bits, float(d_rsu[s]))) * byp * fw
            self.energy[ch] -= fwd_cost
            self.packets_to_rsu += int(byp * fw)

            # attribute the bill: how much of this head's priority forwarding
            # served demand that had no right to assert priority
            self.priority_energy += fwd_cost
            self.priority_energy_false += fwd_cost * (
                1.0 - float(served_gen[s]) / byp)

            # If every reading in the cluster was bypassed there is nothing
            # left to fuse, so refund the fused packet too.
            if total[s] - byp <= 0:
                self.energy[ch] += float(
                    tx_energy(cfg, k, float(d_rsu[s]))) * fw * f

        # --- aggregate-MAC overhead on the fused packet (delta only; 0 by
        # default until Module 3b measures it)
        if cfg.mac_bits:
            extra = (tx_energy(cfg, k + cfg.mac_bits, d_rsu)
                     - tx_energy(cfg, k, d_rsu))
            self.energy[ch_idx] -= extra * forwarded * f

    def _log_emerg(self, sink, agg_delay, served, demand, fw, gen: bool):
        """Record class-2 delay: bypassed at 2 slots, the rest at frame length."""
        if demand <= 0:
            return
        fallback = max(demand - served, 0.0)
        if served > 0:
            sink.append((2.0, served * fw))
        if fallback > 0:
            sink.append((agg_delay, fallback * fw))
        dropped = demand * (1.0 - fw)
        if gen:
            self.emerg_gen_dropped += dropped
            self.readings_delivered_emerg_gen += demand * fw
        else:
            self.emerg_dropped += dropped
            self.readings_delivered_emerg += demand * fw

    def _reap(self) -> None:
        self.energy[self.energy < 0] = 0.0
