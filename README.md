# CHIRP — Cuckoo-inspired Hierarchical Intrusion-Resilient Protocol for VANETs

BTP project: secure routing for VANETs.

**Base paper.** L. Sellami, A. Mchergui, B. Alaya, *"Optimizing vehicular networks
communications through green clustering and data aggregation"*, Cluster Computing
29:16 (2026). DOI 10.1007/s10586-025-05776-1. Proposes **CSGD-NET** — Cuckoo
Search with Levy flights plus a Gaussian random walk for cluster-head election,
with fitness `f = E / (E0 · dist(CH, RSU))`.

## Gaps we close

| # | Gap | Where the paper admits / shows it |
|---|-----|-----------------------------------|
| 1 | No security whatsoever — no authentication, trust, adversary model, or attack evaluation | Security named as a challenge in §2, never addressed |
| 2 | Static topology assumed in a *vehicular* network | §3.3 "topology … remains static"; §4.1 "sensor nodes as stationary entities"; §4.3 concedes it |
| 3 | Fitness uses only residual energy and distance-to-RSU — a liar wins CH | Eq. 9 |
| 4 | CH-aggregated data is never integrity-checked | §3.3.2 |
| 5 | 50×50 m area, 50 rounds, no PDR / delay / overhead metrics | Table 3, Figs. 11–15 |
| 6 | Eq. 9 is described as a minimisation but only works as a maximisation | §3.3.1 vs. Table 4 |

## Modules

1. **Mobility-aware multi-metric CH election** — fitness over residual energy,
   distance-to-RSU, intra-cluster compactness, link expiration time (relative
   velocity/heading), node degree, and trust. Real mobility (highway + urban
   grid, or replayed SUMO traces). Stability-triggered re-clustering.
2. **Trust engine** — Beta-reputation direct trust from watchdog observations,
   recommendation trust weighted by recommender credibility, RSU-anchored global
   trust with decay. Feeds the Cuckoo fitness so a malicious node cannot be
   elected CH. Counters blackhole, greyhole, on-off, bad-mouthing.
3. **Lightweight crypto layer** — pairing-free ECC pseudonym certificates with
   conditional privacy (RSU can de-anonymise a misbehaver), aggregate-MAC over
   CH output, Sybil resistance via rate-limited issuance and RSSI/position
   plausibility. Measured cost: bytes, ms, mJ per operation.
4. **RSU-side IDS** — behavioural features → Random Forest / autoencoder,
   with a revoke → trust-reset → exclude feedback loop. Validated on the
   generated dataset and on the public VeReMi dataset.
5. **Priority traffic** — a second traffic class for emergency vehicles, which
   aggregation is structurally hostile to: fusion forces every reading to wait
   for the whole TDMA frame. Reserved slots bypass fusion, the reservation is a
   finite resource, and a vehicle falsely claiming emergency status is a
   denial-of-service vector against ambulances. Trust bounds it; only an
   authenticated role attribute stops it.

## Status

- [x] Week 1 — simulator core, radio model (Eqs. 9–11), LEACH, LEACH-C,
      CSGD-NET reimplementation, Table 4 reproduction
- [x] Week 1 — HEED, PSO, GA baselines; reproducibility audit (`docs/reproducibility.md`)
- [x] Threat model fixed (`docs/threat_model.md`)
- [x] **Module 1 — mobility + multi-metric CH election** (`docs/module1.md`)
- [x] **Module 2 — trust engine + Layer-A attacks** (`docs/module2.md`)
- [x] **Module 5 — priority traffic + false-priority attack** (`docs/priority.md`)
- [x] **Module 3a — Scyther verification of the authorisation layer**
      (`docs/module3.md`) — 32 claims verified, 8 failing by design. Found and
      fixed a cross-protocol attack between the member-reading and fused-
      aggregate MACs.
- [x] **Module 3b — measured crypto cost** (`docs/module3b.md`) — ECDSA P-256
      sizes and timings from openssl; `sig_bits`=576, `mac_bits`=128 now
      charged. Transmission cost of the whole crypto layer is +0.8–1.6 %;
      **computation cost is ~15× the transmission cost it enables**, which
      the base paper's model cannot see.
- [ ] Week 1 — Figs. 11–15 regenerated
- [ ] Week 3 — Module 2, attack models, Module 4
- [ ] Week 4 — full sweeps, statistics, paper draft, report, slides

## Reproduction result

At the fitted 22 frames/round, mean residual energy per node; paper's Table 4
in brackets.

| Round | LEACH | LEACH-C | CSGD-NET |
|-------|-------|---------|----------|
| 10 | 0.3572 [0.35529] | 0.3579 [0.37000] | 0.3572 [0.32982] |
| 20 | 0.2219 [0.22091] | 0.2157 [0.28339] | 0.2155 [0.26095] |
| 30 | 0.1154 [0.12717] | 0.0745 [0.14785] | 0.0899 [0.15064] |
| 40 | 0.0403 [0.03954] | 0.0027 [0.04387] | 0.0101 [0.07435] |

LEACH matches at RMSE 0.005. **LEACH-C (0.049) and CSGD-NET (0.046) do not** —
ours deplete faster than the paper reports.

We first recorded that as our defect. It is not, and the claim is withdrawn:
under Eqs. (9)–(11) the electronics term is paid identically whichever nodes are
heads, so the amplifier term is the entire budget a clustering algorithm
controls — 0.002 J/node at round 10. Table 4's cross-protocol spread is **20–44×
that budget**, and even a zero-amplifier LEACH-C falls 0.0108 J/node short of
its column. Table 4's LEACH-C and CSGD-NET columns also show drain *rising*
between intervals (+56 %, +60 %), which `alive × cost` cannot do. The only
column that is internally consistent is LEACH — the only one we reproduce.

Alternative readings of "Remaining energy" and both round alignments were tested
and none closes the gap; a ~300 m field would, but Table 3 states 50 × 50 m, so
we did not make that change. See `docs/reproducibility.md` finding 1 and
`python3 src/verify_table4.py`.

Calibrating the one parameter the paper leaves unstated — TDMA frames per round
— to 22 reproduces Table 4's LEACH column to RMSE 0.005. **The base paper's
depletion rate is achievable and its LEACH column is sound**; the arithmetic of
the LEACH-C and CSGD-NET columns is not, per the finding above. See
`docs/reproducibility.md` for the full audit, including three claims we made and
then withdrew under test.

Most of the load-bearing criticisms are not numerical:

1. Eq. 9 does not determine an implementation. Under its literal reading (E =
   "overall residual energy within the vehicular network") the energy term is
   constant within a round, cancels, and CH selection reduces to distance-to-RSU
   alone. Four defensible readings give first-node-death from 9.6 to 22.2 rounds.
2. Eq. 9 has no intra-cluster distance term, so heads are pulled toward the RSU
   and edge members transmit far.
3. Static topology in a vehicular network — the paper's own §4.3 concedes it.
4. No security model at all.
5. Table 4's LEACH-C and CSGD-NET columns cannot be produced by the paper's own
   Eqs. (9)–(11) at Table 3's parameters, so they cannot serve as a baseline.
   We re-implement and report our own measurements instead.

Items 1–2 are what Module 1's multi-metric fitness fixes; 3–4 are Modules 1–4;
5 is why every comparison in this project uses our numbers, not the paper's.

## Run

```bash
pip3 install numpy scipy matplotlib scikit-learn
python3 src/run_baseline.py --seeds 30
```
