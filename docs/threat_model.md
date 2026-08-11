# CHIRP threat model

## Adversary

Internal, authenticated attackers: vehicles holding valid pseudonym certificates
that then deviate. This is the realistic case — an outsider without a valid
certificate is already excluded by Module 3, so the interesting adversary is the
compromised insider. Attackers may act alone or collude (shared attacker set,
coordinated bad-mouthing, Sybil swarms). Attacker fraction sweeps 0–40 %.

We assume the TA and RSUs are honest and the ECC primitives are sound; the
contribution is not new cryptography but the trust + detection layer built on it.

## Two-layer taxonomy

The base paper has no adversary at all, so both layers are new work.

### Layer A — routing / trust layer

Attacks on packet forwarding and on the cluster-head election itself. **Not
present in VeReMi**, which never simulated routing — these exist only in our
simulator, and that is precisely why the simulator is a contribution.

| Attack | Behaviour | Target |
|---|---|---|
| Blackhole | Advertise attractive fitness, win CH, drop 100 % of member data | Aggregation path |
| Greyhole | As above but drop a fraction *p* (0.2–0.8), or drop selectively by source | Evades naive watchdogs |
| Bad-mouthing | Report low recommendation trust for honest nodes | Trust engine |
| Ballot-stuffing | Report high recommendation trust for colluders | Trust engine |
| On-off | Alternate honest and malicious phases to farm trust back | Trust decay/aging |

Blackhole and greyhole are exactly what CSGD-NET's Eq. 9 cannot resist: fitness
reads residual energy and distance only, both self-reported, so an attacker
claiming full battery next to the RSU wins CH every round.

### Layer B — message / data layer

Falsified content in beacons and aggregates. **Maps onto VeReMi Extension**, so
each is both simulated by us and available as real labelled data.

| Family | Variants | VeReMi Ext. |
|---|---|---|
| Position falsification | constant, constant-offset, random, random-offset, eventual-stop | yes |
| Speed falsification | constant, constant-offset, random, random-offset | yes |
| Sybil | grid Sybil (one attacker, many pseudonyms) | yes |
| DoS | flooding, disruptive, DoS-Sybil variants | yes |
| Replay | data replay, stale messages | yes |
| False-data injection | forged aggregate at a compromised CH | ours only |

Note the last row: VeReMi has data replay but no *aggregate* forgery, because it
has no clustering. A compromised CH that fabricates the fused reading is unique
to the CSGD-NET architecture we are extending, and it is what the aggregate-MAC
in Module 3 exists to catch.

Exact VeReMi Extension attacker-type IDs are confirmed against the dataset at
ingest time rather than hard-coded from the paper.

## Defence mapping

| Attack | Caught by | Metric |
|---|---|---|
| Blackhole, greyhole | Module 2 direct trust (watchdog forwarding ratio) | PDR under attack, time-to-detect |
| Bad-mouthing, ballot-stuffing | Module 2 credibility-weighted recommendations | trust MAE for honest nodes |
| On-off | Module 2 trust decay + penalty asymmetry | trust recovery time |
| Sybil | Module 3 rate-limited pseudonyms + RSSI/position plausibility | Sybil detection rate |
| DoS | Module 4 beacon-rate feature | detection rate, FPR |
| Replay, stale | Module 3 timestamp + nonce window | replay acceptance rate |
| Position/speed falsification | Module 4 IDS (kinematic plausibility) | detection rate, FPR, on VeReMi |
| False-data injection | Module 3 aggregate-MAC | forged-aggregate acceptance rate |

## Evaluation

Baselines LEACH, LEACH-C, HEED, PSO, GA, CSGD-NET carry no defence, so under
attack they degrade to whatever the attacker allows — that contrast is the
headline result. 30 seeds, mean ± 95 % CI, Mann-Whitney U for significance.
