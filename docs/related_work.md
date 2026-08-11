# Related work, novelty, and publication

Written from a comparison against three 2026 papers in the same space. Read
this before making any novelty claim in the report or a draft.

## The base paper

L. Sellami, A. Mchergui, B. Alaya, *"Optimizing vehicular networks
communications through green clustering and data aggregation"*, **Cluster
Computing 29:16 (2026)**, DOI 10.1007/s10586-025-05776-1.

**Scoop risk, and it is the one to actually worry about.** Section 5 states:
*"As future direction, we are now working on an optimized version of the present
solution considering the node mobility constraint and thus the network topology
frequent change."* The original authors have announced they are building the
mobility-aware version of CSGD-NET — which is Module 1.

**Mitigation: Module 1 must not be the headline.** Demote it to infrastructure
("we first make CSGD-NET mobility-capable, as its authors indicate is needed")
and lead with the security, priority and audit work. That framing survives even
if their mobility paper lands first — it strengthens the motivation rather than
killing the contribution.

## The three comparison papers

**P1** — K. Satheshkumar, S. Ramalingam, A. Suresh Babu, R. Sarojini, *"Energy
Efficient Trust-Aware Aqua Raptor Optimization Algorithm (TA-ARO) for Secure
Routing in VANETs"*, *Iranian J. Sci. Tech., Trans. Electrical Engineering*
(2026), DOI 10.1007/s40998-026-01150-y. FCKOA-TA-AROA = Optimized Fuzzy C-Means
clustering + Modified Kookaburra Optimization for CH + Trust-Aware Aqua Raptor
Optimization for routing + modified homomorphic encryption.

**P2** — M. Sathik Raja et al., *"Secure Routing and Attack Detection in VANETs
Using BCS-DMCO Optimization"*, *SN Computer Science* (2026) 7:563, DOI
10.1007/s42979-026-05154-7. Binary Cat Swarm Optimization for CH + dependent
Markov chain link-state prediction + trust-aware fitness + AES-128.

**P3** — N. Jaswani, M. Dasgupta, S. Ray, M. S. Obaidat, M. K. Khan, B. Sadoun,
*"A Novel Trust Management Scheme for Secure VANET Routing and Attack
Mitigation"*, *Security and Privacy* (2026) 9:e70241, DOI 10.1002/spy2.70241.
AODV + trust + ECC signcryption.

| | P1 | P2 | P3 | **CHIRP** |
|---|---|---|---|---|
| architecture | cluster + multi-hop route | cluster + route | **no clustering** — AODV | cluster + RSU aggregation |
| CH selection | Kookaburra over energy/mobility/**trust** | Binary Cat Swarm + Markov, **trust in fitness** | n/a | Cuckoo, 6-term fitness + **hard trust gate** |
| trust model | linear weighted sum (PFR, drop, delay, mobility), Eq. 29 | direct + **feedback-credibility-weighted indirect**, equal weights | `+0.001` per good packet; drops > 100 → 0 | **Beta(α,β)**, Laplace smoothing, asymmetric penalty, aging, credibility weighting |
| crypto | homomorphic encryption on trust values | AES-128 session keys | **ECC signcryption** | ECDSA P-256 + role attribute, **Scyther-verified** |
| attacks | Sybil + DoS, 5 % attackers | Sybil/replay/blackhole **as tabular ML on VeReMi** | **blackhole only** | 6 behaviours, swept 0–40 % |
| mobility | random waypoint, MATLAB, 500 nodes | unspecified synthetic | **SUMO + OSM + NS-2.35**, 50 nodes | synthetic highway + urban grid |
| statistics | bar charts, single runs | ± values, no test | single runs | 12–30 seeds, Mann-Whitney/Wilcoxon |
| ablation / negatives | none | none ("equal weights to keep it simple") | none | 4 published negative results |

**P3 is a different problem** — no clustering, no CH election, no energy model.
Not a competitor.

**P2 overlaps in one place that matters**: its Eqs. 17–18 are a
feedback-credibility-weighted indirect trust, the same idea as our Module 2
layer 3. We cannot claim credibility weighting as novel. But P2 never simulates
routing — it downloads VeReMi from Kaggle and runs an 80/20 classifier split,
which is exactly the gap `docs/threat_model.md` names.

**P1 is the real overlap.** Clustering + metaheuristic CH election with trust in
the objective + trust-aware routing + encryption is our four-module stack,
one-for-one. If the abstract reads "we add trust and crypto to a metaheuristic
clustering protocol for VANETs", a reviewer hands you P1.

## Novelty verdict

**As mechanism: mostly not novel.** Be honest about this.

- Trust as a term in a metaheuristic CH fitness — saturated (P1, P2, a decade of
  WSN work).
- Beta reputation — Jøsang & Ismail 2002.
- Credibility-weighted recommendations — P2 does it; standard since Chen's IoT
  trust work.
- ECC pseudonyms with conditional privacy — P3 and a large literature.
- RF/autoencoder IDS on VeReMi — heavily saturated; **P2 is already there**.
  This is why Module 4 is the candidate to cut if time is short.

**As contribution: yes, in five places, none of which is a mechanism.**

1. **Trust-based demotion pays the attacker** (`docs/module2.md`). Detected
   attackers end with 2.0–2.4× the residual energy of honest nodes, because
   exclusion from the CH role spares them the most expensive job in the network.
   Corollary that indicts a literature: *a trust defence cannot be validated on
   energy metrics* — which is exactly what P1's "42 J" and P2's "energy
   balancing index 0.80" headlines do. Not found named anywhere.
2. **Priority is a denial-of-service surface** (`docs/priority.md`). Reserved
   emergency slots are a finite resource a head cannot authenticate, and a
   behavioural detector provably cannot separate a restrained liar from a real
   ambulance. Only the certificate does.
3. **Coverage and deadline latency are in direct opposition.** The clustering
   literature optimises coverage without measuring what it costs deadline-bound
   traffic, because none of it models a class with a deadline.
4. **Crypto's cost is computation, not bytes** (`docs/module3b.md`), and the
   base paper's radio-only model cannot show it.
5. **The reproduction audit** (`docs/reproducibility.md`). Eq. 9 does not
   determine an implementation — four defensible readings give first-node-death
   from 9.6 to 22.2 rounds — and Table 4's LEACH-C and CSGD-NET columns are not
   producible by the paper's own equations. Nothing in P1/P2/P3 approaches this
   standard.

Plus, as method: the controlled-optimiser comparison (CHIRP subclasses
`CSGDNet` and inherits the Cuckoo engine byte-for-byte, so a measured difference
is attributable to the objective), and four published negative results.

## Publication

**Paper A — "CHIRP: a secure trust-aware cuckoo clustering protocol".**
Publishable in the tier P1/P2 occupy (*SN Computer Science*, *Iranian J. Sci.
Tech.*, *Wireless Personal Communications*, *Cluster Computing*). Low risk, low
value, and it competes head-on with P1.

**Paper B — the audit, the free ride, and priority as an attack surface.**
Harder to place, worth more, and it is what has actually been built.

| venue | fit |
|---|---|
| *Vehicular Communications* (Elsevier) | strong — VANET-specific, takes critical/measurement work |
| *Simulation Modelling Practice and Theory* | strong — "published model is under-determined" is its remit |
| IEEE VNC, short paper | strong — fast, right audience, best route to something citable before the deadline |
| *Ad Hoc Networks* / *Computer Networks* | moderate — higher bar, wants more than one novel result |
| ACM TOMACS | moderate — prestigious, slow, would want the simulator as the artefact |

**Remaining blockers, in order.**

1. ~~LEACH-C/CSGD-NET reproduction gap~~ — **resolved**. Diagnosed as a defect
   in the published table, not our implementation, with three independent
   arguments in `docs/reproducibility.md`. No longer a blocker.
2. **Heinzelman radio at VANET distances.** `docs/module1.md` concedes it: d⁴ at
   100–150 m makes absolute lifetimes meaningless. Needs a robustness check
   under a realistic 802.11p path-loss model showing the free-ride and
   intra-term results survive.
3. **Synthetic mobility.** P3 used SUMO + OSM + NS-2.35. Replaying real SUMO
   traces removes an easy objection and is a day or two of work.
4. **Computation energy is measured but not charged.** `docs/module3b.md`
   quantifies it; charging it would move every Module 1 and 2 baseline. A
   deliberate boundary, but a reviewer may ask.

**Timing.** Journal review here is 4–12 months to first decision. IEEE VNC's
short-paper track is the fastest route to something citable before graduation;
keep the journal version for later.

**One thing to handle carefully.** `docs/reproducibility.md` finding 3 observes
that Table 4's HEED/PSO/GA columns are exactly linear, and finding 1 that its
LEACH-C/CSGD-NET columns are non-monotone. Keep both as they are written — an
observation about published numbers with a stated methodological consequence
(the table cannot be a baseline), never an allegation about how they were
produced. Some venues will ask for it to be cut; the paper does not depend on
it, so cut it if asked.

## Caveat on this document

This comparison came from a targeted search, not a systematic review. No paper
duplicating CHIRP was found, but "not found over roughly eight queries" is
weaker than a proper Scopus/IEEE sweep on the exact phrase set. Do that before
submission.
