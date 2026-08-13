# CHIRP — orientation for a fresh session

BTP project: secure, priority-aware clustering for VANETs, built on top of a
published protocol. Read this first, then `README.md`, then the `docs/` file for
whatever you are working on.

## What this project is

We reimplement **CSGD-NET** (Sellami, Mchergui & Alaya, *Cluster Computing*
29:16, 2026, DOI 10.1007/s10586-025-05776-1) — Cuckoo Search with Levy flights
and a Gaussian walk for cluster-head election — and extend it with the things it
has no equivalent of: mobility, trust, cryptography, and priority traffic.

`docs/related_work.md` covers how this differs from the current literature, what
is and is not novel, and where it could be published. **Read it before making
any novelty claim.**

## Layout

```
src/            simulator. run_*.py are experiment drivers; the rest is the model
src/protocols/  LEACH, LEACH-C, HEED, PSO, GA, CSGD-NET (faithful), CHIRP (ours)
formal/         Scyther .spdl models + run_scyther.py
docs/           one file per module, each with results, ablations and negatives
docs/diagrams/  8 SVG architecture/workflow figures, drawn from the results
results/        JSON emitted by the runners; regression_reference.json is special
*.pdf           generated deliverables (extraction, diagrams) — snapshots, not
                canonical; docs/ and results/ are the source of truth
```

**Every table in `docs/` is produced by a committed command.** If you add a
result, add the runner too — do not leave it in an inline script.

Module numbering is historical: **Module 5 (priority) lives in
`docs/priority.md`**, not `docs/module5.md`. Module 4 (RSU-side IDS) is not
built.

## The one invariant that matters

`results/regression_reference.json` fingerprints 55 configurations — three
scenarios × seven protocols × seeds, plus the trust engine under attack — down
to the exact float bits of the energy vector, PDR counters, orphan/intra traces
and trust scores.

```bash
python3 src/regression_gate.py /tmp/now.json
python3 src/regression_gate.py --diff results/regression_reference.json /tmp/now.json
```

**Run this before and after any change to `src/`.** Priority traffic and crypto
are opt-in — they only apply when a `TrafficModel` is attached — so Modules 1
and 2 must stay bit-identical. If the diff is non-empty and you did not intend
it, you have broken the reproduction the whole project rests on.

## Conventions that are deliberate, not accidental

**Negative results are kept, not deleted.** Several config defaults are 0 or
off precisely because the mechanism was tried and made things worse:
`w_survival`, `assoc_let_weight`, `recluster_max_rounds=1`. The code paths stay,
with the evidence in `docs/module1.md`. Do not "clean these up".

**Delay is measured in TDMA slots, never milliseconds.** The simulator has no
channel and no time below the round. A millisecond figure would be invented.
Same for throughput in Mbps, jitter, and multi-hop route latency — the topology
is strictly member → CH → RSU.

**Do not curve-fit to the base paper's Table 4.** Its LEACH-C and CSGD-NET
columns cannot be produced by the paper's own equations at its own parameters —
see `docs/reproducibility.md` finding 1 and `python3 src/verify_table4.py`. A
~300 m field would reproduce them, but Table 3 states 50 × 50 m, so we did not
make that change. Only LEACH is a usable reproduction target.

**Claims are stated at the strength the evidence supports.** Several statements
in `docs/` are explicitly withdrawn corrections. When a result is noise, say so.
When an effect is directional but the magnitude is seed-dependent, do not quote
a number.

## Running things

```bash
pip3 install numpy scipy matplotlib scikit-learn

python3 src/run_baseline.py --seeds 30                       # Table 4 reproduction
python3 src/run_module1.py --scenario urban --seeds 20       # CH election
python3 src/run_module2.py --scenario urban --seeds 12       # trust under attack
python3 src/run_priority.py --scenario urban --seeds 12      # priority + false-priority
python3 src/run_priority.py --scenario urban --seeds 12 --bypass-cost
python3 src/run_priority.py --scenario urban --seeds 12 --sweep-greed
python3 src/run_priority.py --scenario urban --seeds 6  --rounds 40 --coverage-latency
python3 src/run_priority.py --scenario urban --seeds 16 --crypto-decomp
python3 src/crypto_bench.py                                  # crypto sizes/timings
python3 src/verify_table4.py                                 # the Table 4 argument
```

Both scenarios (`urban`, `highway`) matter — several findings only appear when
you compare them, and one (trust gating's false-positive cost) appears in urban
and not on the highway.

**Scyther is not in the repo.** It is a build artifact. Get v1.3.0 from
github.com/cascremers/scyther — it ships a native macOS arm64 binary, no Rosetta
needed despite the tool's reputation — then:

```bash
SCYTHER=/path/to/Scyther/scyther-mac python3 formal/run_scyther.py
```

The runner checks results against the expectations recorded in
`docs/module3.md` and exits non-zero if anything moved.

## State

Done: Module 1 (mobility + multi-metric CH election), Module 2 (trust), Module
3a (Scyther), Module 3b (crypto cost), Module 5 (priority). Both scenarios,
crypto charged, regression gate passing.

Open, and **both need a decision from the user rather than more code**:

- **Module 4** (RSU-side IDS on VeReMi) — not started, and the least novel
  piece. A 2026 paper already does RF-style ML on the same public dataset, and
  VeReMi contains none of the Layer-A attacks this project defends against. The
  candidate to cut. See `docs/related_work.md`.
- **Publication blockers** — an 802.11p path-loss robustness check, and real
  SUMO traces. Neither blocks the BTP; both block a journal submission.

Also open: Figs. 11–15 regeneration, and the write-up.

`docs/handoff.md` carries the full state, the open decisions, and the traps —
read it before starting anything substantial.

## Findings a fresh session would otherwise re-derive

- **Trust-based demotion pays the attacker.** Excluding a misbehaving node from
  the CH role spares it the most expensive job in the network, so detected
  attackers end with 2.0–2.4× the residual energy of honest nodes. A security
  defence cannot be validated on energy metrics. (`docs/module2.md`)
- **Coverage and emergency latency are in direct opposition.** Orphans skip
  fusion and are the lowest-delay path, so a protocol good at coverage is bad at
  deadlines. Module 1's headline win is a latency loss. (`docs/priority.md`)
- **Detection is not mitigation.** The trust engine detected false-priority
  attackers at 0.93–0.96 and changed the outcome not at all, because its only
  lever was CH eligibility and the attack does not require being a head.
- **Behavioural detection bounds priority abuse; only the certificate stops
  it.** At assertion rate 0.50 the attacker is invisible (detection at or below
  the false-positive rate) and still takes ~48 % of maximum deadline damage.
- **Crypto's cost is computation, not bytes.** The per-message signature is
  statistically undetectable in energy terms; ECDSA verification costs ~15× the
  radio energy of the signature it checks. The base paper's model charges radio
  only and so cannot see this. (`docs/module3b.md`)
- **Scyther found a real cross-protocol attack** between the member-reading and
  fused-aggregate MACs, invisible in the simulator where message types are
  Python fields. Fixed with domain-separation tags. (`docs/module3.md`)
