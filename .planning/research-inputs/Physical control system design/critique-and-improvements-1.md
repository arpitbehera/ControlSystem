# Critique and Improvements 1: AMO Control System Design

**Reviewed artifact:** `papers/amo-control-system-design.md` (R2, last revision 2026-05-24)  
**Review date:** 2026-05-25  
**Scope:** Concrete architecture in Part 3, including its dependence on the pattern audit where that dependence changes a design decision. This is not a full re-verification of every comparative-landscape citation.

## Verdict

The proposal has sound architectural instincts: keep pulse timing on OPX+, separate calibration metadata from live control, attach provenance to shots, and measure the external feedback path rather than extrapolating from OPX internal latency. It is not ready to be used as an implementation baseline.

Five issues should block adoption until corrected:

1. The R1 broker-location decision was only partially propagated; the build sequence and failure discussion still prescribe or imply the opposite placement.
2. The illustrated QUA input-stream contract is not internally valid for variable-length move sets and lacks a deterministic timeout/safe-state behavior.
3. No independent hardware safety and interlock path is specified for hung input streams, broker loss, invalid waveforms, or excessive RF/AOD commands.
4. `calibration_id` is used as if it identifies an immutable full parameter snapshot, but the SQL model only describes individual node outputs/registry rows.
5. The raw-data and backup design can lose or orphan scientifically relevant data after a Tower or EliteDesk failure and does not define an atomic shot-commit boundary.

The best next revision is not a rewrite of the technology choices. It is a correction pass that makes the latency path, safety path, snapshot model, durability model, and deployment sequence consistent and testable.

## Findings

### Critical

#### F-01: The broker-host decision is contradictory after revision

**Evidence:** The executive summary and §§3.1-3.2 keep the broker on the Z2 Tower (`papers/amo-control-system-design.md:11`, `:265-274`, `:280-313`). The same document later says `EliteDesk 800 G6 = broker + scheduler + metadata DB` (`:330`) and Phase 0 instructs moving the broker from Tower to EliteDesk (`:944`). Phase 3 also moves the classifier to a Tower RPC service (`:968`) although §3.5 requires it in the broker process on the latency path (`:870-875`).

**Impact:** A team following the phased plan will implement an architecture opposite to the stated latency-first decision and then reintroduce an IPC/RPC hop into the loop.

**Correction:** Choose one decision and apply it everywhere. Given the documented latency-first constraint, retain Tower-resident broker + in-process frame acquisition/GPU pipeline; remove the obsolete EliteDesk broker move and RPC classifier move. Treat the Tower placement as conditional on the latency and driver-feasibility spike in F-08.

#### F-02: The feedback-loop wire contract is invalid or underspecified

**Evidence:** Section 3.5 declares an input vector sized `N_MAX_MOVES * 5`, but Python inserts `params` derived from the actual moves (`:843-866`). QM documents that inserted input-stream data must match the declared stream size. The move count is separately written via `IO1`, so the count and vector do not form one atomic queued message. `advance_input_stream()` can block indefinitely by design (`:804`, `:816`, `:851`), while the failure table accepts a possible hang until reset (`:337`).

**Impact:** The example cannot be treated as a runnable contract. Under late, missing, mismatched, or reordered host updates, the PPU may block or consume inconsistent command data during a physics sequence.

**Correction:** Define a versioned, fixed-width `RearrangementBatchV1` input-stream message containing `protocol_version`, `sequence_no`, `n_moves`, fixed-size padded move storage, `deadline_ticks`, and flags. Do not carry `n_moves` on a separate IO variable. Define the QUA idle/timeout behavior and the only safe waveform on invalid or missing input. Prototype against the lab's pinned QOP/`qm-qua` version before accepting the seam.

**Primary documentation check:** QM QUA input streams and `advance_input_stream()` / `declare_input_stream()`:
<https://docs.quantum-machines.co/1.1.7/qm-qua-sdk/docs/Guides/features/> and
<https://docs.quantum-machines.co/1.2.0/docs/API_references/qua/dsl_main/>.

#### F-03: The design omits a safety plane

**Evidence:** The design specifies process priority, role permissions, recovery, and calibration checks, but not hardware interlocks, RF output clamps, AOD frequency/power bounds enforced below user code, shutter/laser safe states, emergency stop, or a broker/stream watchdog. A stalled `advance_input_stream()` is explicitly possible (`:337`, `:804`, `:851`).

**Impact:** Data-integrity controls are not a substitute for apparatus or personnel safety. A control-stack architecture is incomplete if loss of a Python process or malformed command has no independently enforced safe outcome.

**Correction:** Add a safety layer independent of scheduler/database availability: physical interlocks and inhibit lines, watchdog behavior, bounded OPX waveform/config constraints, default optical/RF safe states, operator emergency stop, restart authorization, and validation tests that intentionally kill the broker and sever the stream during a run.

#### F-04: `calibration_id` is not a reproducible snapshot in the proposed model

**Evidence:** The prose promises one calibration snapshot per shot (`:398`, `:430`, `:459`, `:927-939`). The persistence model describes `calibrations` as node executions and `registry` rows each pointing to a `calibration_id` (`:350-354`, `:892-901`). A run may depend on many registry parameters produced by different node executions. The claimed append-only `registry` also conflicts with maintaining `valid_until` unless closing intervals is a mutation.

**Impact:** A future user cannot reliably recover the exact set of values applied to a shot, particularly during concurrent calibration publication or when only some DAG nodes update.

**Correction:** Separate:

- `calibration_execution`: a node run and measured results.
- `parameter_version`: immutable typed value produced by an execution.
- `calibration_snapshot`: an immutable published set of parameter-version IDs.
- `run.snapshot_id` and `shot.snapshot_id`: the atomically selected set actually used.

Publish a snapshot transactionally only after fitness/approval checks pass. Never reconstruct a shot snapshot using timestamps or the current registry view.

#### F-05: The scientific data durability boundary is not defined

**Evidence:** Raw HDF5 files live on the Tower, and Tower loss can lose in-flight data (`:337`, `:355`). Metadata lives on the EliteDesk; the broker merely "buffers" records while it is down (`:338`) without declaring whether that buffer is durable. WAL shipping from the EliteDesk to the Tower (`:350`) places a database recovery copy on the same machine that is already the raw-data failure domain. A NAS or USB copy is optional.

**Impact:** A successful physical shot may have raw data without a committed database record, a record pointing to a missing file, or both raw data and recovery material lost with one workstation failure.

**Correction:** Define a shot commit protocol and independent backup target:

- Broker first writes raw data and a manifest into a durable local spool with checksums.
- Ingestion commits metadata only after the raw object is durably accepted, or represents explicit `raw_pending`/`raw_lost` states.
- Replicate raw data and database backups to storage outside the Tower and EliteDesk failure domains.
- Set measured recovery point/recovery time objectives and test loss during write, reboot, and disk failure.

### High

#### F-06: The real-time ownership boundary changes within the paper

**Evidence:** Section 3.4 assigns "in-shot occupation-matrix-driven trajectory computation" to Layer 1/OPX+ (`:407`); the executive summary and §3.5 assign trajectory computation to the Tower GPU and only waveform synthesis to OPX+ (`:15`, `:838`).

**Correction:** Replace Layer 1 wording with a single invariant: OPX+ owns deterministic timed execution and waveform generation; the Tower may compute a versioned rearrangement plan before a declared deadline. State whether any fallback/simple trajectory planner remains in QUA.

#### F-07: The proposed 5-year trajectory seam freezes the wrong abstraction

**Evidence:** The durable contract is a flat float array of `(src_x, src_y, tgt_x, tgt_y, t_ramp)` (`:838-879`, `:1000`). This omits units, coordinate frame, concurrency grouping, AOD tone limits, waveform/calibration reference, validation bounds, protocol evolution, command identity, and completion/error reporting.

**Impact:** Moving from approximately 100 atoms to 1000 atoms, simultaneous moves or different AOD control strategies will likely invalidate this tuple format.

**Correction:** Freeze a versioned semantic protocol, not five floats. Include batch/group semantics, site IDs or explicitly defined physical units, applicable snapshot/descriptor hash, constraints, deadline, sequence ID, status/error stream, and extension/version handling. Keep the ability to replace the planner and waveform encoding.

#### F-08: The design commits to architecture before its gating physics/IO experiments

**Evidence:** The unknown `insert_input_stream` latency is acknowledged (`:824-836`, `:1020-1025`), GPUDirect and driver ownership have not been demonstrated in this combined Windows process, and scale-to-1000 is asserted without target-scale timings (`:876-882`). Yet network, schema, and long-lived contracts are prescribed before Phase 3 benchmarking (`:941-990`).

**Correction:** Add Phase 0A before any migration:

1. Pin QOP/`qm-qua`, BitFlow, CUDA, GPU driver, camera SDK, firmware, and Windows versions.
2. Demonstrate camera acquisition into the intended GPU buffer under the actual SDK ownership model.
3. Measure frame-to-AOD-start latency and tails at representative and target-scale payloads.
4. Exercise broker loss and missing/late stream payloads.
5. Decide Tower broker placement and protocol only after written pass/fail thresholds.

#### F-09: Windows process priority and camera-driver ownership require validation, not prescription

**Evidence:** The broker is assigned Windows real-time priority and simultaneously described as owning BitFlow capture while a separate camera driver service owns the SDK (`:296-303`, `:870-875`). The document does not establish how acquisition/control/buffer registration cross that boundary or whether `REALTIME_PRIORITY_CLASS` risks starving driver/system work.

**Correction:** Specify the one process that owns camera configuration, acquisition, and GPU buffer registration during a run; make non-loop access mutually exclusive. Benchmark CPU affinity and priority policies; accept only settings improving p99/p99.9 without dropped frames or system instability. Avoid mandating Windows real-time priority without this result.

#### F-10: OPX management/status reachability contradicts VLAN isolation

**Evidence:** VLAN 50 is L2-only with no router SVI (`:561`, `:571`), but the topology says other hosts can read OPX status through an inter-VLAN L3 hop (`:561`). No such hop exists. Only the Tower broker NIC can reach the enclave under the shown topology.

**Correction:** Choose and document one model:

- Preferred: only a hardened Tower broker/proxy reaches OPX; scheduler/dashboard use a narrow authenticated broker status API over VLAN 10.
- Alternative: a separately filtered management path approved by QM and security review.

Do not route the latency path through the RB3011.

#### F-11: The claimed least-privilege network policy is incomplete

**Evidence:** The RouterOS excerpt allows guest access directly to PostgreSQL and core access to instruments, then has only selected drops (`:738-756`). It does not show a terminal forward drop, a router-input protection policy, a Postgres TLS/auth strategy, a Tower dual-homing anti-routing/ICS rule, or an explicit firewall matrix although deployment acceptance refers to one (`:1133-1137`).

**Correction:** Replace the illustrative rules with a complete policy matrix and generated/testable configuration. Default-deny both routed forwarding and management input; disable forwarding/bridging/Internet Connection Sharing between Tower NICs; expose a read-only API or replicated query store instead of production PostgreSQL to analyst endpoints; specify TLS, authentication, secrets handling, auditing, and update access.

#### F-12: The network configuration is presented as executable but contains unverified or incorrect deployment details

**Evidence:** The port table names `Te0/1-4 SFP` (`:588`), but the WS-C3560G-48TS-S supplies four SFP-based **Gigabit** Ethernet ports, not TenGigabit ports. The RouterOS excerpt contains placeholders and omitted repeated commands (`:732-736`). The OPX/QM-router layout should be explicitly confirmed: QM documentation presents devices and computer on the QM-router local network or a user's router, while this proposal inserts the Cisco switch into the same vendor subnet.

**Correction:** Label the configuration as a template until it has been applied to the exact IOS/RouterOS revisions. Correct interface names from live `show interfaces status`; expand all required rules; add config lint/restore testing; and obtain QM confirmation or demonstrate the third-party L2 switch topology during Phase 0A.

**Primary documentation checks:** Cisco product data identifies 48 copper Gigabit and 4 SFP-based Gigabit ports:
<https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-3560-series-switches/product_data_sheet09186a00801f3d7d.html>.
QM installation guidance:
<https://docs.quantum-machines.co/1.2.0/docs/Hardware/opx%2Binstallation/>.

#### F-13: One HDF5 file per shot is not justified at the target scale

**Evidence:** The proposal correctly criticizes overloading HDF5 as a database (`:208`) but adopts one HDF5 file per shot as a durable convention (`:355`, `:955`, `:997`) without cadence, size, filesystem metadata, ingestion, or analysis benchmarks.

**Correction:** Treat storage layout as an empirically selected implementation behind a stable manifest/schema. Benchmark per-shot HDF5 against per-run chunked HDF5 or Zarr-like chunked storage using expected image cadence and retention. Stabilize identifiers, checksums, dataset meaning, and schema version, not the file granularity.

#### F-14: Provenance omits execution artifacts needed to reproduce a shot

**Evidence:** The chain retains `code_commit_sha`, descriptor and calibration IDs, and `config_hash` (`:407-459`, `:923-939`) but does not commit the compiled QUA program/config bytes, dependency lock/environment, QOP/QM server firmware/software versions, driver/CUDA model versions, uncommitted working-tree state, or analysis artifact/model hash.

**Correction:** Create an immutable `execution_bundle` record or content-addressed archive containing compiled inputs/artifacts and runtime versions. Reference it from every run/shot alongside `snapshot_id` and `device_descriptor_id`. Use a release/build identifier rather than assuming git SHA alone proves the executed code.

#### F-15: Failure handling lacks idempotence and controlled resumption

**Evidence:** A failed shot "may be re-queued" and buffered records are drained after recovery (`:337-338`) without idempotency keys, run state machine, partially executed shot disposition, calibration-publication rollback, or resumption approval.

**Correction:** Define run/shot states (`prepared`, `armed`, `executing`, `raw_spooled`, `committed`, `failed`, `aborted`, `unsafe`) and idempotent submission keys. Never automatically replay a physics shot or publish calibration results after an uncertain execution. Require operator acknowledgement for recovery from interrupted RT work or safety trips.

#### F-16: Calibration DAG failure semantics are backwards

**Evidence:** A fitness failure is said to automatically re-run "its node and downstream nodes" (`:905`).

**Impact:** Downstream nodes should not consume failed output. If previous active values remain valid, executing downstream nodes after an upstream failure can publish inconsistent calibrations.

**Correction:** On failure, retain the last approved snapshot, mark candidate outputs failed, invalidate dependent candidates, and rerun the failed node or its prerequisites according to policy. Only after a candidate passes should downstream recomputation occur and an atomic snapshot be offered for publication.

#### F-17: Access control is a role sketch, not an operational security design

**Evidence:** Analysts are permitted direct data-lake and calibration/DB reads (`:375-399`, `:570`, `:742-743`); automated agents can schedule runs without an approval workflow beyond an allow-list. Key rotation, service identity, credential storage, TLS, audit immutability, and physical/remote boundary are not defined.

**Correction:** Use service-to-service identities, short-lived credentials where feasible, audited scheduler API calls, read-only data publication or replica access, and explicit operator approval for templates capable of applying optical/RF changes. Resolve the ambiguous term "off-lab laptops" when there is stated to be no off-site VPN.

### Medium

#### F-18: NTP is appropriate for metadata ordering, but the stated guarantees need tightening

**Evidence:** NTP is treated as sufficient for host timing (`:357-364`, `:1095-1099`) while ordering is also described as causality. The RB3011 is called stratum 2 whenever it peers upstream, without a policy for upstream loss or clock-quality logging.

**Correction:** State that OPX timestamps establish experimental timing and database/event sequence establishes order; NTP timestamps are observational metadata. Define offset alarm thresholds, upstream-loss behavior, recorded clock health, and an approved internal/institute NTP source rather than relying on public pool access from the apparatus network.

#### F-19: The proposal lacks a requirements and architectural decision record layer

**Evidence:** Decisions are opinionated, but quantitative requirements are mostly deferred to verification items: acceptable rearrangement p99/p99.9, shot rate, array scaling target, allowed data loss, restore time, calibration publication authority, and security boundary are not requirements with owners.

**Correction:** Add a compact requirements table and ADRs for Tower broker placement, feedback protocol, snapshot publication, storage format, and OPX VLAN topology. Each ADR should identify the requirement, alternatives rejected, evidence required, and reversal condition.

#### F-20: Some landscape inferences are stronger than needed for selecting this lab's architecture

**Evidence:** The argument moves from comparisons with cloud/proprietary systems to "field convergence" and durable five-year contracts (`:148-162`, `:984-1011`). The existing provenance already notes vendor-only and PDF-metadata-only claims.

**Correction:** Separate three labels throughout: documented capability, observed open implementation pattern, and local design inference. Use external systems to motivate investigation, not as evidence that a local schema/protocol should be immutable. Re-verify only the sources that remain decision-bearing after the correction pass.

## Improvement Register

This register converts the findings into implementable changes. `P0` items must be resolved before treating the paper as a baseline; `P1` items must be resolved before first integrated experiments; `P2` items should be completed before multi-user or scale-up work.

| ID | Priority | Improvement | Affected sections | Completion evidence |
|---|---:|---|---|---|
| I-01 | P0 | Normalize the Tower-resident broker decision across role table, failure table, Phase 0 and Phase 3. | Exec summary; §§3.1, 3.2, 3.9 | One architecture diagram and one deployment plan with no broker/classifier placement contradictions. |
| I-02 | P0 | Replace the tuple/`IO1` sketch with versioned fixed-width `RearrangementBatchV1` plus response/status protocol. | §§3.4, 3.5, 3.10 | Runnable QUA/Python spike on pinned QOP version; size/sequence/error tests pass. |
| I-03 | P0 | Specify independent safety interlocks, safe states, command bounds and watchdog/trip recovery. | New safety section; §§3.5, 3.7, 3.12 | Reviewed interlock matrix; broker-disconnect and invalid-command tests enter safe state. |
| I-04 | P0 | Replace per-node `calibration_id` interpretation with immutable `snapshot_id` publication model. | §§3.3, 3.4, 3.6, 3.8, 3.10 | Transactional schema; concurrent-publication and historical-replay tests. |
| I-05 | P0 | Define durable shot commit, checksums, independent replication and RPO/RTO. | §§3.2, 3.4, 3.8, 3.12 | Power-loss/write-interruption test; restore from storage outside Tower/EliteDesk. |
| I-06 | P1 | Make the RT/non-RT boundary wording consistent: GPU produces plans; OPX validates/executes timed waveforms. | §§3.0, 3.4, 3.5, 3.7 | Contract review shows no alternate computation ownership. |
| I-07 | P1 | Benchmark the feedback path before freezing hardware placement or five-year protocol semantics. | §§3.5, 3.9, verify list | p50/p95/p99/p99.9/max data at current and projected payloads, with pass/fail threshold. |
| I-08 | P1 | Validate actual camera SDK, BitFlow, CUDA and broker ownership model under Windows. | §§3.1, 3.2, 3.5 | Thirty-minute no-drop acquisition and tail-latency report under competing load. |
| I-09 | P1 | Add run/shot state machine, idempotency and interrupted-run disposition. | §§3.2, 3.4, 3.8 | Fault-injection tests for broker, DB, disk and OPX restarts. |
| I-10 | P1 | Redesign DAG failure/publication semantics to avoid downstream runs on failed candidates. | §3.6 | Failed-node scenario leaves active snapshot unchanged and prevents dependent publication. |
| I-11 | P1 | Define the VLAN 50 management/status access model and harden dual-homed Tower. | §§3.4.1, 3.12 | Verified network diagram; host anti-forwarding checks; authenticated broker status API or approved alternative. |
| I-12 | P1 | Convert switch/router excerpts into validated templates and correct physical port/interface assumptions. | §3.4.1 | Exported known-good configs from actual gear; restore test; QM topology validation. |
| I-13 | P1 | Replace partial ACL examples with a complete default-deny policy and service authentication model. | §§3.3, 3.4.1 | Firewall-policy tests; no production DB exposure to analyst VLAN; audited allowed flows. |
| I-14 | P1 | Store an immutable execution bundle including compiled QUA/config, environment and firmware/model versions. | §§3.4, 3.8, 3.10 | A historical shot can be reconstructed without current registry/source checkout. |
| I-15 | P2 | Benchmark and select raw-data container/file granularity behind a schema-versioned manifest. | §§3.4, 3.8, 3.10 | Cadence/retention/analysis benchmark at projected array size. |
| I-16 | P2 | Expand access control into identity, TLS, secrets, audit and automation-approval requirements. | §§3.3, 3.4.1 | Threat review plus tested role/credential/audit workflow. |
| I-17 | P2 | Clarify clock semantics and record clock health without treating NTP as experimental timing. | §§3.2, 3.12 | Offset/alarm log and upstream-loss procedure. |
| I-18 | P2 | Add requirements and ADRs; downgrade non-decision-bearing comparative claims. | Parts 1-3; provenance | Reviewed requirements/ADR table with owner and reversal gates. |

## Recommended Corrected Architecture

The corrected proposal can remain close to the current design:

1. **Latency domain:** The Z2 Tower owns run-time camera acquisition, registered GPU buffers, classification/planning, the QM client, and a durable local raw-data spool. No general compute work is admitted during armed/executing runs.
2. **Deterministic and safety domain:** OPX+ owns timed waveform execution. It consumes validated `RearrangementBatchV1` messages, enforces allowable bounds and a defined timeout/safe outcome. Independent hardware interlocks can inhibit outputs regardless of Tower or scheduler state.
3. **Control/data domain:** The EliteDesk owns scheduler, identity/audit endpoints and PostgreSQL metadata/calibration publication, but raw-data and database backups replicate to an independent storage target.
4. **Calibration model:** Calibration node execution produces candidates. A reviewed/qualified transaction publishes an immutable `snapshot_id`; every compiled execution and shot points to that snapshot.
5. **Network model:** VLAN 50 remains an unrouted OPX enclave. The Tower is its only application gateway, through a minimal authenticated status/command service on the control VLAN; the Tower cannot route or bridge VLAN 50. Vendor-supported topology and actual switch interfaces are verified before configuration is declared deployable.
6. **Durable provenance:** Every shot identifies its snapshot, descriptor, versioned execution bundle, raw-data checksum/manifest and run/shot state. The storage container can be replaced after benchmark without changing those meanings.

## Recommended Validation Order

| Order | Gate | Why it comes first |
|---:|---|---|
| 1 | Define safety states, interlock inputs/outputs and watchdog behavior. | No latency win justifies operating with undefined failure safety. |
| 2 | Freeze a provisional `RearrangementBatchV1` and demonstrate QUA input-stream correctness. | The present wire sketch is not a reliable implementation contract. |
| 3 | Run the real camera/BitFlow/GPU/QM latency spike on the Tower, including fault injection. | It decides whether the central latency-first placement works. |
| 4 | Correct network reachability/security and validate on actual hardware with QM topology confirmation. | Avoid building services on an inaccessible or unsupported control path. |
| 5 | Implement immutable snapshot publication and execution-bundle provenance. | Subsequent experiments then create interpretable records. |
| 6 | Implement durable raw-data commit and independent restore tests. | Integrated experiments should not create unrecoverable results. |
| 7 | Select file layout and extend to multi-user workflows after load benchmarks. | These are optimization/usability decisions, not initial correctness gates. |

## Preserved Strengths

The following parts should be kept while the above corrections are made:

- The explicit separation of host-side planning from OPX+-timed waveform generation.
- The decision to measure `insert_input_stream` latency on the actual controller rather than apply internal OPX feedback figures to an external loop.
- The use of a calibration dependency graph and the intention to attach calibration provenance to every shot.
- The separation of latency traffic from general instrument and user traffic, subject to corrected reachability and security details.
- The inclusion of restore drills and operator-facing recovery documentation.

## Sources Consulted for This Critique

- `papers/amo-control-system-design.md`
- `papers/amo-control-system-design.provenance.md`
- `outputs/.plans/amo-control-system-design.md`
- `outputs/.drafts/amo-control-system-design-verification.md`
- Quantum Machines, QUA input-stream features: <https://docs.quantum-machines.co/1.1.7/qm-qua-sdk/docs/Guides/features/>
- Quantum Machines, QUA API (`declare_input_stream`, `advance_input_stream`): <https://docs.quantum-machines.co/1.2.0/docs/API_references/qua/dsl_main/>
- Quantum Machines, OPX+ installation/network procedure: <https://docs.quantum-machines.co/1.2.0/docs/Hardware/opx%2Binstallation/>
- Cisco, Catalyst 3560 series product data sheet: <https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-3560-series-switches/product_data_sheet09186a00801f3d7d.html>
