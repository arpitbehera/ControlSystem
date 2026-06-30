# Control-Stack Architecture for a Neutral-Atom Optical-Tweezer Experiment on OPX+

A source-grounded landscape, a pattern audit, and a concrete proposal for scaling from current hardware to ~1000-atom arrays over 3–5 years.

**Status:** Direct-search deep research run, 2026-05-21. Subagent dispatch was blocked in the local runtime; the four research notes (`amo-control-system-design-research-{open-frameworks,neutral-atom-companies,cross-ref,patterns}.md`) were therefore lead-owned direct searches against documented HTML/abstract sources. **PDF parsing was deliberately avoided** per the run rules; where a claim depends on a PDF-only source, that source is cited from search metadata and the dependency is labeled `[doc: PDF metadata only]`.

---

## Executive summary

Three opinionated calls up front, before the evidence:

1. **The OPX broker process lives on the HP Z2 Tower — co-located with the BitFlow framegrabber and the GPU — with strict process discipline.** This is a *latency-first* call (the lab explicitly chose the lower-latency option over failure-domain isolation). QM's Python client (`QuantumMachinesManager`) talks to the OPX cluster over IP and is light enough to share a host with other tight-loop processes [doc — docs.quantum-machines.co/1.3.0/docs/Hardware/network_and_router/, .../API_references/qm_manager_api/]. The countermeasure to anti-pattern A8 ("one fast box does everything") is not relocation; it is **process isolation on the same box** plus moving the scheduler and metadata DB to the EliteDesk 800 G6 so a Tower crash never poisons calibration history. Rationale, process layout, and failure semantics in Part 3.

2. **The rearrangement loop closes on the OPX+ PPU for the AOD waveform, but the trajectory computation lives on the Tower GPU and is shipped to the PPU via QUA input streams.** The PPU owns the analog output end-to-end — there is no way to route waveform samples off-chip in real time — but everything *above* the waveform (image classification, atom assignment, trajectory parameterization) is GPU work. The seam is `declare_input_stream() / advance_input_stream()` on the QUA side and `job.insert_input_stream()` on the Python side [doc — docs.quantum-machines.co/1.2.6/docs/Guides/features/, .../1.3.0/docs/API_references/qua/dsl_main/]. Frames reach the GPU via BitFlow Axion 1xB → GPUDirect for Video (P2P PCIe write to RTX 4000 Ada memory, no CPU bounce) [doc — bitflow.com/technology/support-for-gpu-direct-for-video/, developer.nvidia.com/gpudirectforvideo, lenovopress.lenovo.com/lp2144-thinksystem-nvidia-rtx-4000-ada-20gb-pcie-active-gpu, docs.nvidia.com/cuda/gpudirect-rdma/]. QM's published OPX+ feedback latencies for *internal* conditional logic remain 224 ns / 272 ns [doc — quantum-machines.co/products/opx/]; the external loop budget is set by camera readout, GPU compute, and the Python→PPU TCP hop (§3.5). The Saffman-lab qua-libs example is the prior art but pushes the *occupation matrix* and does trajectory math in QUA [doc — github.com/qua-platform/qua-libs/.../AMO/Use Case 1]; the proposed scheme is a strictly more flexible implementation of the same "loop closes on the PPU" principle.

3. **Adopt a calibration DAG (à la Google Optimus / QUAlibrate) as the *5-year-survival* seam.** This is the one interface contract that should not be rebuilt every 2–3 years. The pattern is Kelly 2018 [arxiv.org/abs/1803.03226], productized in QUAlibrate's `QualibrationNode` / `QualibrationGraph` / `QualibrationOrchestrator` / `QualibrationLibrary` [doc — qualibrate-docs.quantum-machines.co/calibration_graphs/, .../calibration_nodes/]. The hard architectural commitment is *not* to QUAlibrate the library (its source is now private and you cannot patch it [doc — github.com/qua-platform/qualibrate]) but to the data shape: nodes that update registry parameters, edges that encode dependencies, per-node provenance attached to each shot.

The rest of this document defends those three calls and addresses the seven hardware-architecture decisions you flagged.

---

# Part 1 — Landscape (source-grounded)

## 1.0 Comparative table

Five-axis comparison. **Inference is marked.** Sources for each row are in the per-system sections below and in `outputs/.drafts/amo-control-system-design-research-{open-frameworks,neutral-atom-companies,cross-ref}.md`.

| System | RT / non-RT boundary | Experiment description | Calibration mgmt | Data layer | Known weaknesses |
|---|---|---|---|---|---|
| **ARTIQ / Sinara** | Kernel (compiled subset of Python on FPGA soft-/hardcore CPU coupled to RTIO gateware) ↔ host Python. DRTIO extends to master/satellite over 1 Gbps+ link. [doc] | `EnvExperiment` subclass; `@kernel` methods; static AOT compile. [doc] | "Datasets" with `broadcast/persist/archive` flags. LMDB persistent store + per-run HDF5. [doc] | HDF5 per run, always saved even on failure. [doc] | Channel scaling needs DRTIO + Sinara MicroTCA. HDF5 overhead on tiny datasets (issue #1345). [doc] |
| **labscript-suite** | RT pushed into pseudoclock hardware. Compile is host-side; execution is BLACS-driven from HDF5 shot files. No Python in timed loop. [doc] | Pure-Python labscript file → connection table → HDF5 instructions per shot. `runmanager` substitutes globals. [doc] | No first-class calibration store. `runmanager` globals + `lyse` analysis routines write back globals. [doc] | One HDF5 per shot. lyse augments. Filesystem is the database. [doc] | Slowest pseudoclock sets cadence (issue #112). In-shot Python feedback is a long-standing feature request (issue #18). [doc] |
| **OPX / QUA + QUAlibrate** | QUA program compiled to PPU FPGA bytecode ↔ Python client via `QuantumMachinesManager`. PPU "positions classical computing resources as close as possible to the quantum hardware." [doc] | QUA DSL (Python builder API → protobuf config); `play / measure / assign / if_ / for_`. `input_stream`/`output_stream` for runtime data. [doc] | QUAlibrate: `QualibrationNode`/`Graph`/`Orchestrator`/`Library`. DAG-based. [doc] | Stream processing pipeline materializes data server-side, then to user PC. Persistence is the lab's problem. [doc] | QUAlibrate source moved to private repo [doc]. Docs versioning sprawl across QOP 1.x/2.x/3.x. Total vendor coupling. |
| **QuEra (Aquila)** | Cloud-batch; user submits via AWS Braket / Bloqade. Internal RT layer not publicly described. [doc + inference] | Bloqade SDK: Builder → Bloqade AST (Py & Jl) → emulator IR / QuEra IR / Braket IR. [doc] | Not publicly described. Three-zone reconfigurable architecture (Bluvstein 2023) is the published blueprint. [doc] | AWS Braket result objects. [doc] | Analog-only (Aquila). 256-qubit cap as of 2023 whitepaper. Cloud only. [doc] |
| **Pasqal (Fresnel)** | Cloud-batch. Pulser is a sequence builder; cloud SDK ships `batch`/`job`. Internal RT layer not public. [doc + inference] | `Sequence(register, device)`; `Device` enforces constraints at construct time. [doc] | Device parameters published by Pasqal. Internal cadence not public. [doc + inference] | Cloud batches → SDK. Emulator backends (EMU_TN, EMU_FREE). `strict_validation` opt-in. [doc] | Cloud-only. Emulator-vs-hardware divergence is acknowledged. `max_runs` per device is a published hard limit. [doc] |
| **Atom Computing (AC1000)** | Internal control system; publicly opaque. Job listings confirm a serious internal stack. [doc] | No public DSL. Capability list cites "real-time conditional branching, MCM with reset & reuse." [doc] | Not public. [inference] | Not public; access via Microsoft cloud or on-prem. [doc + inference] | Stack is closed; 1180-atom claim is vendor-announced; independent peer-reviewed benchmarks use 256 atoms (Yb-171). [doc] |
| **Quantinuum H-series** | Named two-layer split: "tasking and operations" ↔ "machine control and real-time execution." [doc] Guppy/HUGR for Helios adds Python-embedded language for dynamic transport + conditional branches. [doc] | OpenQASM / pyTKET; H2 racetrack with 8 gate zones, transport plans via bubble-sort. [doc] | Internal; published cadence in user docs. MCMR is a pyTKET compiler pass. [doc] | Per-job results. [inference] | Cloud-only; transport-time bottleneck. Closed stack. [doc + inference] |
| **IBM Qiskit Runtime** | Primitives (Sampler/Estimator V2) and Sessions in front of cloud backends. Dynamic circuits supported. [doc] | Circuit IR + `PrimitiveV2`. [doc] | `IBMBackend.calibration_id` + `BackendProperties` exposes T1/T2/readout/gate error per qubit/edge. [doc] | `PrimitiveResult`/`EstimatorResult`; sessions group jobs. [doc] | V1→V2 migration disruptive. Docs spread across multiple roots. [doc] |
| **Google calibration graph (Optimus)** | Offline / between jobs. Per-job snapshot retrievable post-hoc via Quantum Engine. [doc] | Cirq circuits. [doc] | DAG of nodes that update "registry parameters"; edges = bootstrapping dependencies; "calibration reduced to graph traversal." [doc — Kelly 2018, arxiv:1803.03226; Klimov 2024, arxiv:2308.02321] | Per-job calibration metrics stored by Quantum Engine. [doc] | Optimus is a method, not shipped software. Klimov 2024 acknowledges exponentially expanding parameter space is the core problem. [doc] |

## 1.1 ARTIQ / Sinara

**RT/non-RT boundary.** ARTIQ defines an explicit *kernel/host* split. `@kernel` methods are statically compiled and shipped to the "core device" — a Kasli / Metlino / earlier KC705 with a soft- or hardcore CPU "tightly coupled with the so-called RTIO core, which runs in gateware and provides precision timing" [doc — m-labs.hk/artiq/manual/core_device.html]. The host (Python) handles "the vast arsenal of diverse laboratory hardware which interfaces with and is controlled from a typical PC" [doc — m-labs.hk/artiq/manual-beta/rtio.html]. DRTIO extends RTIO across master + satellite core devices over a 1 Gbps+ optical/copper link; "remote channels are then accessible in kernels on the master device exactly like local channels" [doc — m-labs.hk/artiq/manual/using_drtio_subkernels.html, github.com/m-labs/artiq/wiki/DRTIO].

**Experiment description.** Experiments derive from `EnvExperiment`. The `@kernel` decorator is the seam; calls from Python land cross into compiled FPGA-side code through the `core` attribute [doc — m-labs.hk/artiq/manual/getting_started_core.html]. Compilation is static, ahead-of-time. This shape is the gold standard for "Python-shaped at the surface, deterministic underneath" and is the right reference when designing your own QUA-side IR.

**Calibration management.** ARTIQ's "datasets" double as the calibration store and the shot-output store. `set_dataset(..., broadcast=True, persist=True, archive=True)` controls visibility, persistence, and per-run archival. Persistent datasets are LMDB-backed [doc — m-labs.hk/artiq/manual-legacy/releases.html, /using_data_interfaces.html]. *Calibration is just data*; this matches pattern P5. The weakness is also visible from the docs: a dataset is a flat key namespace, not a typed graph of relationships — i.e. ARTIQ does **not** ship the Optimus DAG [inference from negative search of m-labs.hk/artiq/manual].

**Data layer.** "Experiment results are now always saved to HDF5, even if `run()` fails" [doc — releases]. Issue #1345 admits the HDF5 overhead is real for scalar-heavy work — useful evidence that picking the right file format for *small* records matters.

**Known weaknesses (documented).** Scaling channel count past one core device requires DRTIO and Sinara MicroTCA gear [doc — github.com/sinara-hw/meta/wiki/uTCA]. Sinara entry-cost is non-trivial. There is no first-class calibration DAG — you would have to build one above the dataset layer yourself.

## 1.2 labscript-suite

**RT/non-RT boundary.** labscript pushes the RT boundary *down into pseudoclock hardware*. The labscript file is pure Python that, at compile time, produces hardware instruction tables written to an HDF5 shot file [doc — docs.labscriptsuite.org/projects/runmanager/.../usage/]. Execution is BLACS-driven: each `BLACS_worker` reads the shot's instruction table and programs its instrument; timing is arbitrated by a `PseudoclockDevice` [doc — docs.labscriptsuite.org/projects/blacs/.../components/, .../shot-management/]. **There is no Python in the timed loop.**

**Experiment description.** Connection table built from `Device(name, parent_device, connection, …)` calls. `PseudoclockDevice` at the top; `IntermediateDevice`s hang off clock lines; output channels hang off intermediates [doc — labscript.base.Device, .../connection_table/, labscript.core.IntermediateDevice]. The connection table is *the* artifact that defines hardware identity; BLACS rejects a shot whose connection table doesn't match the running lab [doc — /blacs/shot-management/]. This is the canonical *hardware abstraction layer* pattern (P3), and the canonical *validate at submit time* pattern (P7).

**Calibration management.** No first-class store. `runmanager` manages typed globals (scalars, lists for grid expansion); `lyse` analysis routines can update globals between shots [doc — runmanager usage, lyse introduction]. Calibrations end up as globals via convention rather than contract — workable for small labs, dangerous at 1000-atom scale because there's no DAG of dependencies.

**Data layer.** Per-shot HDF5 file. lyse "gets your code running on experimental data as it is acquired" [doc — lyse introduction]. The filesystem is the database — works to a point.

**Known weaknesses (documented).** Two recurring pain points the maintainers acknowledge:
- *Slow component dominates whole-sequence timing.* Issue #112 (2025): NI 6739 + PulseBlaster forced into the slower device's cadence [doc — github.com/labscript-suite/labscript/issues/112].
- *In-shot feedback is not native.* Issue #18 has an explicit, open feature request for "execution of small or time-critical scripts within the context of an individual labscript shot" with the example "images acquired → feedback to magnetic field for the next shot" [doc — github.com/labscript-suite/labscript/issues/18]. This is exactly the rearrangement use case; labscript is *deliberately* not the right tool for it.

The 2013 paper by Starkman et al. (arXiv:1303.0080, HTML mirror at ar5iv) frames labscript as a "scripted" middle ground between general-purpose-language stacks and GUI sequencers [doc].

## 1.3 OPX / QUA / QUAlibrate

**RT/non-RT boundary.** The OPX+'s Pulse Processing Unit (PPU) is "an FPGA-based processing unit comprised of multiple waveform generators … positioning classical computing resources as close as possible to the quantum hardware" [doc — quantum-machines.co/technology/pulse-processing-unit/]. QUA programs are compiled and shipped via `QuantumMachinesManager` over IP through the QM Router [doc — docs.quantum-machines.co/1.3.0/docs/Hardware/network_and_router/, .../API_references/qm_manager_api/]. QM publishes 224 ns conditional and 272 ns parametric feedback latency [doc — quantum-machines.co/products/opx/]. Python never enters the timed loop.

**Experiment description.** QUA "defines the sequence of: 1) Multiple OPX timing and latencies, 2) Pulses sent to the quantum device, 3) Measurements of pulses returning from the quantum device, 4) Real-time classical calculations done on the measured data, 5) Real-time classical decisions and flow control" [doc — docs.quantum-machines.co/1.3.0/docs/Introduction/qua_overview/]. `input_stream`/`output_stream` move data in and out of running programs [doc — docs.quantum-machines.co/1.3.0/docs/API_references/qm_opx1000_job_api/].

**Calibration management.** QUAlibrate is explicit and matches the Optimus pattern: "Tuning up a qubit … involves executing a sequence of calibration nodes. The next calibration node to be executed may depend on the measurement outcome of one or more previous nodes … represented using a directed acyclic graph (DAG) together with an orchestrator." [doc — qualibrate-docs.quantum-machines.co/calibration_graphs/]. Core types: `QualibrationNode`, `QualibrationGraph`, `QualibrationOrchestrator`, `QualibrationLibrary` [doc — github.com/qua-platform/qualibrate-core, .../calibration_nodes/, .../advanced_calibration_graphs/]. Recommended API: `QualibrationGraph.build()` context manager.

**Data layer.** API references show `compile`, `execute`, and streamed I/O via `qm.api.v2.job_api`. QM's stream processing buffers on PPU, processes server-side, then surfaces to user PC [doc — docs.quantum-machines.co/1.3.0/docs/Guides/stream_proc/]. There is no built-in HDF5 / Postgres opinion comparable to ARTIQ datasets or labscript shot files.

**Known weaknesses (documented).** 
- *Source closed.* "QUAlibrate is free to use, however the source code has been moved to a private repository" [doc — github.com/qua-platform/qualibrate]. You can use it; you cannot patch it. Treat it like an external service.
- *Docs versioning sprawl.* `docs.quantum-machines.co/1.2.0/`, `/1.2.3/`, `/1.2.4/`, `/1.3.0/` coexist with QOP 2.x (OPX+) vs QOP 3.x (OPX1000) API drift; Job API V2 is OPX1000-only [doc — same docs root]. As an OPX+ shop on QOP 2.x you cannot rely on docs you find via search engines pointing at the right version.
- *Vendor coupling.* QUA is not portable off OPX. The PPU bytecode is not a published target.

## 1.4 QuEra (Aquila / Bloqade)

**RT/non-RT boundary.** Cloud-batch. Aquila is "a 'field-programmable qubit array' (FPQA) operated as an analog Hamiltonian simulator on a user-configurable architecture" [doc — Aquila 1.0 whitepaper, arxiv.org/abs/2306.11727, PDF not parsed per workflow rule]. There is no published RT/non-RT seam description; what is observable is *batch-in / shots-out* via AWS Braket [doc — bloqade.quera.com/dev/analog/].

**Experiment description.** Bloqade's design philosophy is openly published: a multi-IR compiler stack — Builder → Bloqade AST (Python and Julia) → emulator IR or hardware IR (QuEra IR, Braket IR) [doc — bloqade.quera.com/v0.30.0/analog/contributing/design-philosophy-and-architecture/]. This is the cleanest published "experiment description as data + compiler" in any of the three companies and is the right reference if you want a multi-IR target later.

**Calibration management.** Not publicly described. What *is* documented from the founders' group (Bluvstein 2023, Nature, "Logical quantum processor based on reconfigurable atom arrays") is a three-zone architecture (storage / entangling / readout) with mid-circuit readout in a separate physical zone and atom shuttling between zones [doc — nature.com/articles/s41586-023-06927-3]. The 2023 PRX paper from the Wisconsin group (Graham et al., "Midcircuit Measurements on a Single-Species Neutral Alkali Atom Quantum Processor") is the directly relevant single-species realization [doc — journals.aps.org/prx/abstract/10.1103/PhysRevX.13.041051].

**Data layer.** Braket SDK; persistence beyond the user's bucket is the user's problem.

**Known weaknesses (documented + inferred).** Analog-only on Aquila; ≤256 qubits in the 2023 whitepaper; cloud-only submission; no on-prem.

## 1.5 Pasqal (Fresnel / Pulser)

**RT/non-RT boundary.** User-visible boundary is sharply defined: Pulser builds `Sequence` locally; cloud SDK ships `batch` of `job`s with `runs` and `variables`; the queue API is REST-exposed (`/api/v1/devices/{dt_name}/queue`) [doc — docs.pasqal.com/cloud/{first-job,batches,fresnel-job,api/core/...}]. Internal RT layer not public.

**Experiment description.** A `Sequence` "combines: a Register that defines the relative positions of the atoms involved in the computation; a Device that dictates the physical constraints the program must respect; Channels, selected from the Device, that define which states are used in the computation; a schedule of operations, wherein Pulses and other operations are placed in the Channels" [doc — docs.pasqal.com/pulser/sequence/]. The `Device` enforces constraints at construct time — *static validation against published device parameters* [doc — docs.pasqal.com/pulser/hardware/]. **This is the single best published example in the landscape of "experiment description as data + validating compiler" and is the model I recommend you copy.**

**Calibration management.** What's visible is one-way: Pasqal updates `Device` objects; users get those constraints back through Pulser. Internal cadence is not public.

**Data layer.** Cloud batches/jobs → SDK. Emulators (EMU_TN, EMU_FREE) accept the same `Sequence` interface; `strict_validation` opt-in flag is documented as the mechanism to catch hardware-vs-emulator divergence [doc — docs.pasqal.com/cloud/pasqal-cloud/usage/advanced_usage/]. This is **pattern P7 + P11 (validate at submit + emulator with strict mode)** in one place.

**Known weaknesses (documented).** `max_runs` per device is a hard published limit. Emulator-vs-hardware divergence requires explicit opt-in to catch. No real-time in-shot Python.

## 1.6 Atom Computing (AC1000 / Phoenix / Yb-171)

**RT/non-RT boundary.** Internal stack is publicly opaque. The Built In posting for "Senior Software Engineer - Control Systems" is the strongest indirect signal the stack is non-trivial and Python-friendly [doc — builtin.com/job/senior-software-engineer-control-systems/8421921]. AC1000 product page lists capabilities: "1,200+ physical qubits, all-to-all qubit connectivity, … mid-circuit measurement with qubit reuse and reset and real-time conditional branching" [doc — atom-computing.com/ac1000/].

**Experiment description / calibration / data.** No public DSL or compiler; no published calibration cadence; no public data-path documentation. All three are inference.

**Known weaknesses.** Almost nothing about the control software is publicly verifiable; the 1180-atom figure was a vendor announcement (Oct 2023) ahead of independent peer-reviewed full-system benchmarks; published peer-reviewed work from the team uses 256 Yb-171 atoms (2024, arxiv.org/abs/2411.11822). The stack is closed; nothing to import.

**Note on vendor-vs-peer-reviewed claims.** The AC1000 capability list ("1,200+ physical qubits, all-to-all qubit connectivity, mid-circuit measurement with qubit reuse and reset and real-time conditional branching") is a vendor product-page claim [doc — atom-computing.com/ac1000/]. The closest independently peer-reviewed point of comparison from the same group is the 2024 Yb-171 paper at 256 atoms with 24 logical qubits [doc — arxiv.org/html/2411.11822v2]. Treat the capability claim as documented vendor copy, not as an independently verified system specification.

## 1.7 Quantinuum H-series (cross-ref)

The H-series user docs are unusually concrete. "System Model H2 is a transport-based quantum processor with a linear race-track geometry. Random qubit access utilizes all 8 gate zones as swapping regions … layers of the circuit are executed sequentially, with transport primitives used to arrange the ions so that qubits scheduled to interact are co-located in a gate zone." [doc — docs.quantinuum.com/systems/user_guide/hardware_user_guide/h2.html]

**Two named layers.** "The tasking and operations layer manages and allocates access to the system, whilst the machine control and real-time execution layer manage[s] …" [doc — docs.quantinuum.com/.../operation.html]. **Take this naming; it survives 5+ years.**

**MCMR as a compiler pass.** "The MCMR package, built as a pyTKET compiler pass, is designed to reduce the number of qubits required for executing many types of quantum algorithms" [doc — quantinuum.com/blog/features-and-benefits-...]. Treat MCMR as a *sequence transformation*, not an ad-hoc per-experiment macro.

**Guppy / HUGR.** "Guppy is a high-level quantum programming language embedded in python. Guppy allows Helios users to benefit from dynamical transport for programs with conditional branches … arbitrary real-time classical arithmetic and logic including native `FOR` and `WHILE` loops, early exit, and conditional branches with native `IF`(`ELSE`) statements. The user compiles a Guppy program to a Hierarchical Unified Graph (HUGR)." [doc — docs.quantinuum.com/.../workflow.html]. This is the explicit model for "Python-shaped above the RT FPGA boundary, with a typed IR underneath" — a worthwhile reference for if/when QUA gets too thin.

## 1.8 IBM Qiskit Runtime (cross-ref)

The user-facing architecture is *primitives + sessions*. V2 `Sampler` and `Estimator` are the only entry points; a `Session` "allows you to make iterative calls to the quantum computer more efficiently" [doc — quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/runtime-service, /guides/primitives, /guides/run-jobs-session]. `IBMBackend.calibration_id` ties a job to a specific calibration snapshot; `BackendProperties` exposes per-qubit T1/T2, readout error, gate error [doc — quantum.cloud.ibm.com/.../ibm-backend, github.com/Qiskit/qiskit-ibm-runtime/blob/main/qiskit_ibm_runtime/models/backend_properties.py].

**Take the `BackendProperties + calibration_id` model.** It is the cleanest provenance seam in the landscape: a job *carries* the calibration snapshot ID it was run against, and you can retrieve it later. This is what Part 3's provenance proposal copies.

Known churn: V1→V2 migration was disruptive; multiple doc roots (`docs.quantum.ibm.com`, `quantum.cloud.ibm.com`, `qiskit.github.io/qiskit-ibm-runtime`). Cost of being a cloud surface.

## 1.9 Google calibration graph — "Optimus" (cross-ref)

Kelly et al. 2018, *Physical qubit calibration on a directed acyclic graph* [doc — arxiv.org/abs/1803.03226]: "calibration is reduced to a graph traversal problem." The Sycamore supremacy paper supplement names the system **Optimus**:

> "We use the 'Optimus' formulation … where each calibration is a node in a directed acyclic graph that updates one or more registry parameters, and the bootstrapping nature of calibration sequences is represented as directed edges between nodes." [doc — ar5iv.labs.arxiv.org/html/1910.11333, §VI.1.2, and FIG. S10 "Optimus calibration graph for Sycamore"]

Klimov et al. 2024 (arxiv.org/abs/2308.02321, articles/s41467-024-46623-y) extends this with closed-loop scheduling across an "exponentially expanding configuration space" and reports a ~3.7× reduction in error vs no optimization (accept as published claim; not independently re-verified) [doc].

Cirq's user-side surface: "Calibrations are also available for past jobs" [doc — quantumai.google/cirq/google/calibration]. The pattern is consistent with Qiskit's `BackendProperties + calibration_id`.

**The directly reusable seams are P4 + P5 + P6 (DAG of calibration nodes, registry parameters as the unit of update, per-job snapshot for provenance).** QUAlibrate already implements this shape; you have to commit to the *data contract*, not the QUAlibrate library.

## 1.10 What the landscape converges on

Strip out modality differences and what survives across ARTIQ, labscript-suite, OPX/QUA, Pasqal, Quantinuum, IBM, and Google is:

1. **A named RT/non-RT boundary.** Every durable stack has one. The labels vary; the existence does not.
2. **Experiment description as data, compiled to RT bytecode.** Builder pattern + validation. (Pulser, Bloqade, QUA, labscript connection table, ARTIQ kernel compile.)
3. **A calibration store separate from source control.** ARTIQ datasets, labscript globals, IBM BackendProperties, Cirq Quantum Engine.
4. **Calibration as a DAG.** Optimus + QUAlibrate, both with `registry parameters` as the unit of update.
5. **Per-job / per-shot calibration snapshot attached to results.** Cirq, Qiskit. The provenance seam.
6. **Driver process per instrument under a central orchestrator.** labscript BLACS_worker, ARTIQ device controllers, QM cluster.
7. **A pseudoclock/sequencer as the timing root, not the host clock.** labscript PseudoclockDevice, ARTIQ RTIO, OPX PPU.

These are the seven seams Part 3 will preserve. Everything else is implementation detail and rebuildable.

---

# Part 2 — Patterns and anti-patterns

## 2.1 Patterns (load-bearing architectural seams)

Numbered for cross-reference from Part 3. Each row is concrete and source-anchored.

| # | Pattern | Concrete example | Tag |
|---|---|---|---|
| P1 | **Explicit RT/non-RT boundary as a contract** | ARTIQ kernel/host (`@kernel`); QUA-on-PPU vs Python client; Quantinuum tasking/ops vs machine-control & RT execution | [doc] |
| P2 | **Experiment description as data, compiled to RT bytecode** | Pulser `Sequence(register, device)` validated by `Device`; Bloqade multi-IR; QUA `with program()` → protobuf | [doc] |
| P3 | **Hardware-abstraction layer: "what experiment wants" ≠ "which DAC channel"** | labscript `Device(name, parent_device, connection, …)`; Pasqal `Channel`s from `Device` | [doc] |
| P4 | **Calibration as a DAG of nodes updating a registry** | Kelly 2018 Optimus; Klimov 2024; QUAlibrate `QualibrationNode`/`Graph`/`Orchestrator` | [doc] |
| P5 | **Calibration values out of source control** | ARTIQ datasets in LMDB + per-run HDF5; labscript globals in HDF5 | [doc] |
| P6 | **Per-job calibration snapshot attached to results** | Cirq "calibrations are also available for past jobs"; IBMBackend `calibration_id`; ARTIQ HDF5 archives datasets used | [doc] |
| P7 | **Validate at submit time against device descriptor** | Pulser `Device` enforces `min_atom_distance` etc.; BLACS rejects mismatched connection tables | [doc] |
| P8 | **Sessions/batches as resource-reservation unit** | Qiskit Runtime Session; Pasqal batches (`open=True`/`close()`) | [doc] |
| P9 | **Driver process per instrument; central orchestrator** | labscript BLACS_worker; ARTIQ device controllers; QM cluster | [doc] |
| P10 | **Pseudoclock as the timing root, not the host clock** | labscript PseudoclockDevice; ARTIQ RTIO gateware; OPX PPU | [doc] |
| P11 | **Three-zone reconfigurable-array architecture (storage / entangling / readout)** | Bluvstein 2023 Nature; Graham 2023 PRX (single-species MCM) | [doc] |
| P12 | **Camera→classifier→AOD-waveform loop closed at FPGA, not Python** | Saffman-lab QM use case (FPGA delivers occupation matrix to PPU registers; QUA computes trajectories; PPU drives AOD); OPX+ 224/272 ns feedback; LLRS framegrabber + RDMA | [doc] |
| P13 | **Stream processing between RT and host** | QUA stream_processing: PPU buffer → server-side pipeline → user PC | [doc] |
| P14 | **Analysis-as-side-effect-on-globals** | lyse routines update runmanager globals between shots | [doc] |
| P15 | **Modular open hardware ecosystem decoupled from any one lab** | Sinara (CERN OHL); arXiv:2408.13652 modular ultracold control | [doc] |
| P16 | **Distributed RT via point-to-point sync** | ARTIQ DRTIO; OPX+ cluster "no central controller architecture" | [doc] |
| P17 | **Multi-IR compiler with emulator backend** | Bloqade (Builder → AST → emulator IR / QuEra IR / Braket IR); Pulser + EMU_TN/EMU_FREE | [doc] |
| P18 | **Compiler pass for sequence transformations (MCMR, DD)** | Quantinuum pyTKET MCMR pass | [doc] |
| P19 | **UUID + structured metadata per dataset** | qDrive/QHarbor UUIDs + scope_name + custom IDs; QubiCSV with git-like versioning | [doc] |
| P20 | **Interface contracts that survive personnel changes** | Conway's Law original (Conway 1968); bus-factor literature | [doc + inference] |

## 2.2 Anti-patterns

| # | Anti-pattern | Concrete example | Tag |
|---|---|---|---|
| A1 | **Calibration values in git** | `pi_pulse_amplitude.py` carrying a number; every retune = a commit | [inference + P5] |
| A2 | **Hidden global state in instrument drivers** | Driver caches "last-set" value; silently no-ops on duplicate set; first symptom is one missing shot after power-cycle | [inference] |
| A3 | **Python in the timed loop** | DIY stacks that route the timed loop through Python desync on GC or thread preemption; labscript Issue #18 confirms it is deliberately disallowed | [doc + inference] |
| A4 | **Bespoke GUI per experiment** | New postdoc → new GUI → new untested IO layer. Each adds bus-factor mass | [inference + P9] |
| A5 | **Untested bring-up code** | Driver exercised only on the live, single instance of the instrument; first sign of breakage is also first day of being unable to reproduce a result | [inference] |
| A6 | **Calibration timestamp ≠ shot timestamp** | "Which calibration was active for this shot?" — if you can't answer from the file alone, you've lost reproducibility. The fix is P6 | [inference + P6] |
| A7 | **Same Python process owns RT-IO + GUI + analysis** | One slow plot blocks the experiment thread | [inference + P9] |
| A8 | **"One fast box does everything"** | A single workstation owns the OPX broker, framegrabber, SLM-adjacent orchestration, dashboard, GPU compute. Failure of any of those bricks the whole experiment. **This is the most relevant anti-pattern to your current setup.** | [inference] |
| A9 | **Undocumented hardware dependencies** | A device needs a specific PCIe slot, driver version, hidden registry key; postdoc has graduated; bus-factor literature confirms this is the default failure mode of small teams with a star engineer | [doc + inference] |
| A10 | **Bypassing the sequencer for "quick fixes"** | "Toggle this DO directly from Python" works the first time and creates a race condition that bites in 3 months | [inference] |
| A11 | **No emulator / dry-run mode** | Forces every test to consume real shots. Pulser's emulators and ARTIQ's `--dry-run`-style modes prevent this | [doc] |
| A12 | **HDF5-as-database** | One HDF5 per shot is fine for analysis; one HDF5 as source of truth for calibration *and* configuration *and* shot data muddles concerns; labscript pays this price | [inference] |
| A13 | **Driver carries the sequencer's clock model** | A device that "knows" what the sequencer is doing leaks coupling. labscript's `parent_device` + ClockLine avoids this | [inference + P10] |
| A14 | **Schemas defined by example, not by contract** | If "the shape" of a shot file is whatever the latest postdoc wrote, every analysis script is a guess. Pulser's `Device` and labscript's connection table check are the antidotes | [doc — P3, P7] |
| A15 | **No formal handoff between user code and RT** | If a user can submit arbitrary Python that runs on the RT box, you've lost determinism. ARTIQ enforces this via static compile; QUA enforces it because Python is the *builder*, not the *executor* | [inference] |
| A16 | **One pseudoclock, slowest device sets cadence** | labscript Issue #112: NI 6739 + PulseBlaster forced into the slowest device's cadence | [doc] |
| A17 | **"Just one more spreadsheet"** | The lab spreadsheet that tracks "which calibration is current" is the canonical bus-factor risk. Replace with P4 + P6 | [inference] |
| A18 | **Microservices for one lab** | Six Python processes talking over HTTP to themselves on localhost when in-process function calls would have sufficed | [inference] |
| A19 | **Premature web UI** | Browser dashboards that block the experiment thread for a render frame; or re-fetch all shots every redraw | [inference] |
| A20 | **Conway's-Law-shaped architecture** | Control software shape mirrors the postdoc/PI/grad-student org chart. When a postdoc leaves, the *module shape* changes. Conway 1968 predicts this; the fix is interface contracts that survive personnel changes | [doc + inference] |

## 2.3 SWE-concept verdicts for AMO neutral-atom tweezer control

| Concept | Verdict | Why | Concrete for AMO lab |
|---|---|---|---|
| **State machines** | **Load-bearing** | Instrument layer is fundamentally stateful (laser locked/unlocked, MOT loaded/not, atoms present/absent) | A locking system as `UNLOCKED → LOCKING → LOCKED → DRIFTING → UNLOCKED` is auditable; a boolean `is_locked` is not |
| **Event-driven** | **Mixed** | Event-driven between hosts is fine (camera image ready → classifier consumes). Event-driven inside the RT loop is wrong — the RT loop must be schedule-driven | OK: framegrabber publishes "frame_ready" → classifier consumes. NOT OK: QUA schedules a pulse on a Python event |
| **Plug-ins** | **Load-bearing** | New instruments arrive regularly. labscript_devices, ARTIQ device DB, Pulser Channel registry all show plug-ins are what survive | A new camera should be added by implementing a `Camera` interface, not by modifying the orchestrator |
| **SOA (coarse)** | **Load-bearing** | Coarse SOA (drivers, scheduler, dashboard, data store as separate processes/services) maps cleanly to multi-machine reality | A `metadata_db` service is sensible |
| **Microservices** | **Cargo-culted** | A single lab needs neither independent deployment nor polyglot stacks nor HTTP between in-process callers | If you find yourself adding a service registry in one room with 8 users, stop |
| **Deterministic execution (at RT layer)** | **Load-bearing** | Pulse-level timing requires it; ARTIQ RTIO, QUA PPU, labscript pseudoclock all enforce it | Determinism *above* the RT layer (scheduler/dashboard) is unnecessary and expensive |
| **Observability** | **Load-bearing** | A 1000-atom run will fail in subtle ways — drift in one beam, misaligned classifier, AOD harmonic. Without trace/metric/log at three layers you cannot debug | Structured logs per driver; OpenTelemetry-style spans on the scheduler; calibration-graph node histories — all required at 1000-atom scale |
| **Reproducibility** | **Load-bearing** | The whole point of a control system. P5 + P6 + UUID metadata (P19) are the minimum | Tools like QBOM / devqubit / QubiCSV exist because the field acknowledges the gap; you should copy the *idea*, not necessarily the tool |
| **Testability** | **Load-bearing, asymmetric** | RT-layer testability is hard (needs hardware); compiler / scheduler / connection-table-validator testability is easy and high-value | A test that loads every driver in emulated mode and asserts the connection-table check passes is one of the highest-value tests you can write |

---

# Part 3 — Concrete proposal

This part is opinionated. Every decision traces to a constraint you stated, a documented pattern (Px above), or a documented anti-pattern (Ax above).

## 3.0 Architecture overview

The proposal is six layers, deliberately stacked so each one is a re-buildable independent contract:

```
Layer 6: Access & UI (lab terminals, browser dashboard, scripts)
Layer 5: Scheduler & orchestrator (calibration DAG runner, job queue, run runner)
Layer 4: Experiment-description & compiler (validating builder → QUA bytecode + non-RT instructions)
Layer 3: Calibration store + metadata DB + raw data lake (registry parameters; shot UUID; calibration_id)
Layer 2: Device-server layer (one process per instrument-class; uniform driver interface)
Layer 1: RT layer (OPX+ PPU; AOD via OPX analog out; framegrabber→PPU FIFO for in-shot feedback)
Layer 0: Physics (atoms, lasers, optics, vacuum)
```

The seams between layers are the interface contracts. **The seams must survive 5+ years; the *implementations* inside any layer can be rebuilt every 2–3 years.**

Mapping to documented patterns:
- Layer 1↔2 seam = P1 (RT/non-RT boundary as a contract) + P12 (FPGA-closed feedback) + P13 (stream processing)
- Layer 2 = P9 (driver process per instrument) + P3 (hardware-abstraction)
- Layer 3 = P4 (calibration DAG) + P5 (calibration out of git) + P6 (per-job snapshot) + P19 (UUID metadata)
- Layer 4 = P2 (description as data) + P7 (validate at submit) + P17 (multi-IR + emulator) + P18 (compiler passes)
- Layer 5 = P8 (sessions/batches) + P4 (DAG runner)
- Layer 6 = P9 (uniform UI/driver split; one GUI per role, many experiments)

## 3.1 Layer-to-machine assignment

Hardware inventory you gave me, reassigned. The current assignment puts too much on the Z2 Tower (anti-pattern A8). Proposed:

| Machine | Spec recap | Proposed role | Why |
|---|---|---|---|
| **HP Z2 Tower (Ultra 9 285K, 128 GB, RTX 4000 Ada, 4 TB NVMe + 12 TB HDD, Win 11 Pro)** | High-CPU/RAM, big NVMe, GPU, has BitFlow Axion 1xB framegrabber for Andor iXon, currently OPX broker | **Broker process + Andor/framegrabber driver + GPU rearrangement pipeline + data lake.** Runs the latency-critical *broker process* (QM client + BitFlow capture + CUDA pipeline + `insert_input_stream`) under strict process discipline (§3.2). | (a) Andor iXon + BitFlow Axion 1xB is a PCIe card and cannot be relocated. (b) GPUDirect for Video requires camera DMA peer-to-peer to the GPU on the *same* PCIe topology — the framegrabber and the RTX 4000 Ada must share this host [doc — bitflow.com/products/camera-link/axion-1xb/, developer.nvidia.com/gpudirectforvideo]. (c) Co-locating the broker with the GPU pipeline avoids any cross-host hop in the rearrangement loop. (d) 12 TB HDD is the raw-data lake. **A8 risk** is real and is bounded by the process-isolation discipline in §3.2 and by keeping the calibration registry off this host. |
| **HP Z2 Mini G1i (Ultra 9 285, 64 GB, RTX 4000 SFF Ada, 2 TB NVMe, Win 11 Pro), SLM via HDMI** | Same-class CPU as Tower, GPU, modern NVMe, SLM HDMI plugged | **SLM host + holography compute + emulator host.** | (a) SLM is HDMI-bound; cannot relocate. (b) GPU + 64 GB RAM is enough to run the Gerchberg-Saxton / WPGS hologram pipelines (cf. arxiv.org/abs/2604.04600) [doc — abstract] without leaning on Tower. (c) Acts as a *second* compute service so the Tower is not a single point of failure for general GPU work outside the rearrangement loop. |
| **HP EliteDesk 800 G6 (i7-10700, 64 GB, Win 10 LTSC)** | Mid-tier CPU, no GPU, lots of RAM | **Scheduler / orchestrator + metadata DB + calibration registry + read-only dashboard backend.** Headless. **No OPX broker process here.** | (a) Calibration registry on a *different* host from the broker means a Tower crash never poisons calibration history. (b) Scheduler can refuse new submissions when the broker is unreachable, providing a clean back-pressure surface. (c) Postgres on local NVMe; WAL-shipping to Tower 12 TB HDD nightly. (d) Win 10 LTSC has the longest support runway on hand; lowest churn risk. |
| **Lenovo ThinkCentre (i5-10500T, 16 GB, Win 10 LTSC)** | Low-spec but stable | **Device-server host for slow / GigE instruments** (Princeton Instruments ProEM HS1024 GigE, 2× DMK 33GX545 GigE, 2× DMK 33GX264 GigE, Thorlabs CS165MU1 USB, PCO Pixelfly USB ×2 — moved here). | (a) GigE/USB cameras don't need GPU. (b) Isolates slow-image-IO traffic from the Tower's NIC. (c) 16 GB is enough for buffered acquisition. |
| **OPX+ + lab Ethernet switch** | As-is | **RT layer** (Layer 1). Owns the AOD waveform synthesis end-to-end. | User constraint: AOD is OPX-analog-driven; no computer in the loop for waveform generation. |

**Net change vs current state:** OPX broker *stays* on the Tower for latency. Tower additionally hosts the framegrabber, the rearrangement GPU pipeline, and the raw-data lake — with strict process isolation (§3.2) to bound A8 risk. Scheduler, calibration registry, and metadata DB move to the EliteDesk 800 G6. SLM and holography compute stay on the Mini. Slow GigE/USB cameras consolidate on the ThinkCentre. This addresses your decisions #1 (broker host = Tower, with the broker as a *single, latency-pinned* Python process — not the box's only job, but its highest-priority one), #2 (Tower also serves general GPU compute when no run is in flight), #3 (Mini PCs are hybrid: ThinkCentre device-server, EliteDesk service-server, Mini hybrid).

## 3.2 The seven decisions, answered

### Decision 1 — OPX broker host: dedicated box, or co-located with the GPU pipeline?

**Recommendation: broker process runs on the HP Z2 Tower, co-located with the BitFlow Axion 1xB framegrabber, the Andor iXon driver, and the RTX 4000 Ada CUDA pipeline. The scheduler, calibration registry, and metadata DB stay on the EliteDesk 800 G6.** This is a *latency-first* choice (the lab explicitly chose minimum-latency feedback over failure-domain isolation; the latter is recovered partially via process isolation on the Tower and physical separation of the calibration registry).

Rationale:
- The rearrangement loop (§3.5) is the dominant latency-critical path in the system. The pipeline is Andor → BitFlow Axion 1xB → GPU (GPUDirect) → CUDA compute → `insert_input_stream` → OPX. Every cross-host hop in that chain costs at minimum a TCP round-trip; co-locating the broker with the GPU pipeline removes one such hop.
- The Axion 1xB's StreamSync DMA engine and BitFlow's GPUDirect for Video support let the framegrabber DMA frames directly into RTX 4000 Ada memory without a CPU bounce [doc — bitflow.com/products/camera-link/axion-1xb/, bitflow.com/technology/support-for-gpu-direct-for-video/, developer.nvidia.com/gpudirectforvideo]. This only works when framegrabber and GPU share a PCIe topology, i.e. live in the same chassis.
- RTX 4000 Ada explicitly supports both GPUDirect for Video and GPUDirect RDMA per the Lenovo and PNY datasheets [doc — lenovopress.lenovo.com/lp2144-thinksystem-nvidia-rtx-4000-ada-20gb-pcie-active-gpu, pny.com/.../PNY-NVIDIA-RTX-4000-Ada-Generation-Datasheet.pdf]. NVIDIA confirms GPUDirect RDMA is "available on both Tesla and Quadro GPUs" [doc — docs.nvidia.com/cuda/gpudirect-rdma/].
- A8 risk ("one fast box does everything") is countered by **process isolation on the Tower** plus **physical separation of the calibration registry on the EliteDesk**. A Tower crash kills the in-flight shot; it does not corrupt or lose the calibration history.
- An LLRS-style escape (framegrabber + RDMA directly to an AWG, bypassing the host entirely) would require the Hamamatsu Orca Quest 2 + Quantum Machines OP-NIC combination, which the lab has ruled out as not viable. The GPU-RDMA-into-input-stream pipeline is the best achievable latency on the available hardware.

Process discipline on the Tower (mandatory for this to work):
- **Broker process** (single Python interpreter): owns `QuantumMachinesManager`, the BitFlow capture, the CUDA pipeline, and `insert_input_stream`. Pinned CPU affinity (a small subset of the 24 P-cores), Windows real-time priority class. **No GUI. No other Python.**
- **Andor camera driver service** (separate Windows service): the SDK runs here. Exposes a thin API for non-loop snaps (operator GUI, diagnostics). During a run it is *not* in the loop; the framegrabber-to-GPU path does not traverse it.
- **Compute service** (separate Tower process, same GPU): handles non-loop GPU work (re-analysis, offline calibration analyses). **Operator-visible mutex prevents it from running concurrently with a run.**
- **Data lake writer** (separate Tower process): receives shot records from broker via shared-memory queue and writes per-shot HDF5 to 12 TB HDD. **Asynchronous from the loop.**

What lives on the broker host (HP Z2 Tower):
- Broker process (above)
- Andor camera driver service
- BitFlow Axion 1xB framegrabber driver
- Compute service (non-loop GPU work)
- Data lake writer + 12 TB HDD

What lives on the EliteDesk 800 G6 instead:
- Scheduler / orchestrator process (Layer 5)
- Calibration DAG runner
- PostgreSQL (metadata DB; Layer 3) — including the calibration registry
- Configuration registry (current `Device` descriptor)
- Read-only dashboard backend

What lives on the Mini:
- SLM driver + HDMI link
- Holography compute (Gerchberg–Saxton / WPGS)
- Pulser-style emulator for dry-runs

### Decision 2 — GPU workstation: master, or compute service?

**Recommendation: compute service.** The Tower is invoked over RPC from any other host that needs CPU/GPU work. Concretely:
- A `compute_service` daemon (single process; bind to the lab subnet) exposes a small typed RPC (gRPC or simple HTTP + msgpack) with verbs: `classify(image_bytes, classifier_id) → occupation_matrix`, `recompute_hologram(target_geometry, weights) → slm_frame`, `reanalyze_run(run_uuid, analysis_id) → result`.
- The same daemon exposes per-call provenance: input UUIDs, model ID, code commit SHA, elapsed time.
- The framegrabber / Andor remain on this machine because PCIe pins them.

This is **SOA-coarse (load-bearing) + microservices-cargo-culted (avoided)** — one service that lives in one process on one box, called as if it were local.

The risk this avoids: if the Tower is master, every other host depends on it. If it's a compute service, the lab can degrade gracefully: rearrangement still works (loop is closed on OPX); only post-shot CPU/GPU work is delayed.

### Decision 3 — Mini PCs: device-servers, service-servers, or hybrid? Behaviour when one dies?

**Recommendation: hybrid, with explicit failure modes.**

- **HP Z2 Mini** = SLM host + holography compute + emulator host. Service-server *and* device-server.
- **EliteDesk 800 G6** = broker + scheduler + metadata DB. Service-server (no instruments pinned).
- **ThinkCentre** = GigE/USB camera device-server. Device-server only.

Failure semantics:

| Host that dies | Effect on a running experiment | Recovery |
|---|---|---|
| **HP Z2 Tower** (broker + Andor + framegrabber + GPU pipeline + data lake) | **In-flight rearrangement shot fails** — broker is gone, the QUA program will block on `advance_input_stream()` waiting for the next vector and either time out or hang until cluster reset. Any pre-shot QUA jobs already loaded into the PPU that do not consume input streams continue (the QM Job API is documented as asynchronous; the running program executes independently of the Python client [doc — docs.quantum-machines.co/1.3.0/docs/API_references/qm_opx1000_job_api/]; **verify on your firmware version before relying on this**). Data-lake writes for the in-flight shot are lost. **Calibration registry on EliteDesk is unaffected; calibration history survives.** | Restart Tower (power-cycle <5 min). Broker reconnects to OPX via `QuantumMachinesManager`. The scheduler on EliteDesk holds the run queue; failed shot is marked and may be re-queued by the operator. Data lake on local HDD; rolling backups to NAS / external USB. |
| **HP EliteDesk 800 G6** (scheduler + Postgres + calibration registry) | In-flight QUA job on the OPX continues (broker on Tower is alive; calibration values for the current shot were already resolved at submission time). Broker buffers shot records locally until DB is back. **New jobs cannot be scheduled**; calibration DAG halts. | Restart EliteDesk. Postgres on local NVMe + WAL replay. Broker drains its local buffer into Postgres. Calibration DAG resumes from the last committed node. ETA: <10 min if disk is fine. |
| **HP Z2 Mini** (SLM + holography + emulator) | SLM frame freezes at last value (HDMI is stateful). Holography pipeline pauses. Emulator pauses. Rearrangement on the AOD path is **unaffected**. | Restart Mini. Recompute current hologram from current `Device` descriptor + current geometry. |
| **ThinkCentre** (slow cameras) | Slow-image shots fail; primary atom-imaging continues (Andor on Tower). Diagnostics dim. | Restart ThinkCentre. |
| **OPX+** | Running shot fails; experiment halts. | Restart OPX cluster via QM admin panel. Re-establish config via `QuantumMachinesManager`. |
| **Lab Ethernet switch** | Everything stops. The TCP path between broker (Tower) and OPX cluster is gone; the rearrangement loop and any scheduler→broker handoff stops. | Switch reboot; all hosts reconnect; PostgreSQL holds shot-id sequence. |

This is the answer to decision #3 and to your "failure model for each named hardware element" sub-question.

### Decision 4 — Location and backup story for metadata DB, calibration store, raw data lake

**Recommendation:**

- **Metadata DB:** PostgreSQL on EliteDesk 800 G6 local NVMe. WAL-shipping to Tower 12 TB HDD nightly (point-in-time recovery). Daily logical backups (`pg_dump`) to NAS or USB rotated weekly.
  - Schema: `runs (uuid, start_ts, end_ts, code_commit_sha, calibration_id, user, …)`, `shots (uuid, run_uuid, shot_index, qua_job_id, raw_path, …)`, `calibrations (id, parent_id, node_results …)`, `device_descriptor (id, content_jsonb, valid_from, valid_until)`.
  - Why Postgres not SQLite: multi-user, concurrent commits from device-server processes, mature WAL.
  - Why not InfluxDB for metadata: InfluxDB is great for *time-series* (drift, lock errors) but a relational engine with JSON columns is better for relational provenance [doc — docs.influxdata.com/influxdb3/clustered/reference/internals/storage-engine/ describes Influx as columnar/time-series; relational join over shot↔calibration↔device is a Postgres job by construction].
- **Calibration store:** Postgres-backed registry table + per-node result records. Each "registry parameter" is a row with `parameter_name, value_jsonb, calibration_id, valid_from, valid_until, generated_by_node, generated_by_run`. This is the Optimus pattern translated to SQL.
- **Raw data lake:** Tower 12 TB HDD. One HDF5 per shot under a directory tree `<year>/<month>/<day>/<run_uuid>/shot_<index>.h5`. Rolling rsync to NAS (if available) or hot-swap USB. Each shot file embeds its `run_uuid`, `calibration_id`, `code_commit_sha` as HDF5 attributes (P19).

### Decision 5 — Time sync: NTP everywhere, or PTP somewhere?

**Recommendation: NTP everywhere; PTP nowhere on the current hardware.**

- Pulse-level timing is OPX's job. The OPX cluster handles intra-cluster sync internally [doc — docs.quantum-machines.co/1.2.3/docs/Hardware/opx%2Binstallation/]. You do not need PTP between hosts for that.
- Between hosts the only timing relationship is *causality* — shot N's metadata commits before run N+1 starts. NTP at ~10 ms accuracy is sufficient.
- **PTP is not achievable on the installed gear.** Cisco PTP support starts at the Catalyst 3650/3850 generation [doc — cisco.com/c/en/us/td/docs/switches/lan/catalyst3650/.../configuring_precision_time_protocol__ptp_.html]; the WS-C3560G-48TS-S has only QoS-based prioritization. MikroTik RB3011 does not act as a PTP grandmaster natively. Upgrading to PTP would require a new switch (e.g. Catalyst IE-3300 / 3650) plus a grandmaster (e.g. Meinberg LANTIME). Out of scope.
- Concrete setup: the RB3011 runs a local stratum-2 NTP server peering upstream (`pool.ntp.org` or institute NTP); all hosts sync to it. Drift goal: ±10 ms. Per-host config in §3.4.1 and fallback procedure in §3.12.

### Decision 6 — Network layout: flat lab subnet, VLANs by function, separate management plane?

**Recommendation: VLANs by function from day one, on a Cisco Catalyst WS-C3560G-48TS-S access switch with a MikroTik RB3011UiAS-RM as router/firewall/NTP/DHCP. Detailed architecture in §3.4.1.**

- The choice of installed networking gear (3560G + RB3011) makes VLAN segregation cheap; the operational cost of *not* segregating is real once the OPX cluster, GigE cameras, and lab hosts all share a broadcast domain.
- Five VLANs: `lab-core` (10), `instruments` (20), `mgmt` (30), `guest` (40), `opx-rt` (50). VLAN 50 is L2-only, trust-enclave; no SVI on the RB3011; OPX traffic never traverses the router (anti-pattern A8 mitigation at the network layer).
- The QM router stays in place on VLAN 50 in bridge mode, treated as required vendor topology [doc — docs.quantum-machines.co/1.3.0/docs/Hardware/network_and_router/] until QM confirms a supported bypass. The Z2 Tower is dual-homed (broker NIC on VLAN 50, control NIC on VLAN 10).
- Full port plan, switch config, RouterOS config, jitter analysis, application-layer acceptance tests, and operational recovery procedures are in §3.4.1 and §3.12.

### Decision 7 — User access path

**Recommendation:**
- **Lab terminals** (i.e. dashboards on Tower / Mini / EliteDesk during runs): role = `operator`. Direct read/write to the scheduler API on EliteDesk via a thin Python CLI.
- **Off-lab laptops**: role = `analyst`. Read-only access to the metadata DB and the data lake over the lab subnet's wired-only access. No off-site VPN.
- **Automated jobs**: role = `agent`. Token-based, narrow set of verbs (`schedule_run`, `read_calibration`, no `apply_calibration` without operator countersign).
- **SSH**: enabled to EliteDesk and Tower only, key-only, no password auth. Not for steering the experiment — for `pg_dump`, rsync, diagnostics.
- **No browser-based control** from outside the lab subnet. (Non-goal: cloud, multi-site.)

Access-control verb matrix below in §3.3.

## 3.3 Access control: role × verb matrix

| Role / Verb | `view_dashboards` | `read_calibration` | `read_data_lake` | `schedule_run` | `interrupt_run` | `apply_calibration` | `mutate_device_descriptor` | `restart_service` | `add_user` |
|---|---|---|---|---|---|---|---|---|---|
| `analyst` (off-lab) | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `operator` (lab terminal, daily user) | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `senior_operator` (postdoc-level) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| `admin` (one or two people) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `agent` (automated jobs) | ✗ | ✓ | ✗ | ✓ (scoped) | ✗ | ✗ | ✗ | ✗ | ✗ |

The **blast-radius bound** comes from three things:
1. `mutate_device_descriptor` is admin-only and writes a new versioned row (`valid_from`, `valid_until`) — never overwrites. Every shot remembers which descriptor it ran against (P7 + P6). A wrong descriptor breaks future shots, not past ones.
2. `apply_calibration` requires `senior_operator` and writes a new `calibration_id`. Old shots keep their old `calibration_id`. **A wrong calibration cannot retroactively poison existing data.**
3. `schedule_run` for `agent` is scoped to a fixed allowed-list of run templates; a misconfigured agent cannot submit arbitrary QUA.

## 3.4 Interface sketches for each seam

These are *contracts*, not implementations. Each one should survive 5+ years.

### Seam: Layer 1 ↔ Layer 2 (RT ↔ device-server)

The RT layer (OPX+) owns: AOD waveform synthesis, all timed digital/analog IO that participates in the timed loop, the in-shot occupation-matrix-driven trajectory computation. The device-server layer (Layer 2) owns everything else.

```python
# Layer 2 → Layer 1 contract: submit a compiled QUA job and stream results back.
@dataclass(frozen=True)
class RtJobSubmission:
    qua_program_blob: bytes          # protobuf serialized
    config_hash: str                 # SHA-256 of the QmConfig used to compile
    input_streams: dict[str, ndarray]  # named inputs to push via input_stream
    expected_outputs: list[str]      # names of streams to surface
    run_uuid: UUID
    calibration_id: int
    timeout_s: float

@dataclass(frozen=True)
class RtJobResult:
    run_uuid: UUID
    shot_index: int
    outputs: dict[str, ndarray]      # per-stream materialized arrays
    timing: dict[str, float]         # PPU clock ticks, queue depth, …
    status: Literal["ok", "rt_error", "rt_timeout"]
```

**Why this shape:** the config_hash + run_uuid + calibration_id pin the shot to a calibration snapshot (P6). `expected_outputs` makes the *consumer* declare what they want, so the stream processing pipeline can prune what gets serialized (P13).

### Seam: Layer 2 ↔ Layer 3 (device-server ↔ data + calibration)

Driver processes write shot results to two places: the metadata DB (small, indexed, queryable) and the raw data lake (big arrays, HDF5).

```python
# Inserting a shot record (metadata)
shots.insert(
    shot_uuid=...,
    run_uuid=...,
    shot_index=...,
    started_at=..., ended_at=...,
    qua_job_id=...,
    calibration_id=...,         # FK -> calibrations.id
    code_commit_sha=...,        # the build that produced the QUA
    config_descriptor_id=...,   # FK -> device_descriptors.id
    raw_path="2026/05/21/<run_uuid>/shot_0042.h5",
    status="ok",
)

# In the HDF5 sibling file (raw data lake):
#  /image_andor (uint16 array)
#  /image_proem (uint16 array, optional)
#  /occupation_matrix (uint8 array)
#  /qua_outputs/<stream_name>
#  attrs: shot_uuid, run_uuid, calibration_id, code_commit_sha, config_descriptor_id
```

**Why this shape:** the HDF5 self-identifies (P6 + P19); the DB lets you query "give me every shot where calibration_id is X and code_commit_sha is Y" without scanning files. This is the exact pattern Cirq + IBM expose for cloud jobs (P6).

### Seam: Layer 3 ↔ Layer 4 (calibration registry ↔ compiler)

The compiler (Layer 4) reads the *current* device descriptor and the *current* registry parameters; it produces a QUA `QmConfig` plus non-RT instructions for the device-server layer.

```python
class DeviceDescriptor:
    """Pasqal-shaped: machine-readable description of physical constraints."""
    valid_from: datetime
    channels: dict[str, ChannelSpec]   # per AOD axis, per laser, per camera
    geometry: ArraySpec                # max atoms, lattice constants
    timing: TimingSpec                 # min slice, jitter budgets
    constraints: list[Constraint]      # e.g. "AOD freq in [80, 120] MHz"

class CalibrationSnapshot:
    """Optimus-shaped registry view."""
    id: int
    generated_at: datetime
    parent_id: int | None
    parameters: dict[str, JSON]        # e.g. "pi_pulse_amp_clock" -> 0.347

class CompiledRun:
    qm_config_proto: bytes
    qua_program_proto: bytes
    config_hash: str
    non_rt_plan: dict[str, list[NonRtInstruction]]   # per device-server queue
```

The compiler **rejects** any run whose request violates the descriptor (P7). It does this *before* the QUA build, so the device-server queue never sees a bad submission. The emulator backend (P17) compiles to a different target but takes the same input.

### Seam: Layer 4 ↔ Layer 5 (compiler ↔ scheduler)

The scheduler talks in `Runs` and `CalibrationDAGTraversals`. A `Run` is a high-level intent. A `CalibrationDAGTraversal` is a chain of QUAlibrate-style nodes.

```python
class RunRequest:
    user: str
    template_name: str            # e.g. "rydberg_blockade_demo"
    parameters: dict[str, JSON]   # scanned + fixed
    required_calibration: list[str] | None  # which registry params must be fresh

class DagNode:
    name: str
    inputs: list[str]             # registry params consumed
    outputs: list[str]            # registry params updated
    qua_template: str             # or path to template
    max_age_s: float              # how stale before re-run is forced

class DagTraversal:
    nodes: list[DagNode]
    plan: list[list[str]]         # topo-sorted layers
```

When the scheduler receives a `RunRequest`, it (a) checks freshness of `required_calibration` against `max_age_s`, (b) submits a `CalibrationDAGTraversal` for any stale params, then (c) submits the `Run`. Calibration runs *are* runs with a different template type. This unifies the DAG runner with the run runner.

### Seam: Layer 5 ↔ Layer 6 (scheduler ↔ UI / users)

Two channels:
- **Operator CLI / lab-terminal dashboard:** a thin Python client that calls `scheduler.submit(RunRequest)`, `scheduler.status(run_uuid)`, `scheduler.interrupt(run_uuid)`, `scheduler.list_jobs(...)`. Authenticates via local OS user → role mapping (Postgres `pg_ident.conf` style).
- **Off-lab read-only browser dashboard:** static HTML + a tiny FastAPI/Flask app on the EliteDesk that queries Postgres only. No mutating verbs.

**Do not** build a browser-based "control" UI in Phase 1. Anti-pattern A19.

## 3.4.1 Network architecture and switch/router programming

This section is the concrete deployment plan for the lab's networking hardware: **Cisco Catalyst WS-C3560G-48TS-S** (access switch, IP Base, 48× GbE + 4× SFP, 32 Gbps non-blocking fabric, IOS 15.0(2)SE-class) and **MikroTik RB3011UiAS-RM** (router, 10× GbE + 1× SFP, RouterOS 7, dual QCA8337 switch chips). It is the answer to your stated decisions #5 and #6 grounded in the actual installed gear.

### 3.4.1.1 Verified capability constraints

Three constraints from vendor docs shape the design and need to be flagged before any commands are issued:

1. **No PTP on either device.** Cisco PTP support starts at the 3650/3850 generation [doc — cisco.com/c/en/us/td/docs/switches/lan/catalyst3650/.../configuring_precision_time_protocol__ptp_.html]; the WS-C3560G-48TS-S has only QoS-based prioritization. Sub-µs cross-host sync via the network is not achievable on this gear. NTP (per Decision 5) is the floor.
2. **3560G jumbo MTU is global, not per-port.** "You cannot change the MTU on an individual interface. You must set the MTU globally. Reset the switch afterwards for the MTU change to take effect" [doc — networkengineering.stackexchange.com/questions/2779/cisco-3560g-mtu-options; Cisco 3560 software config guide]. Mitigation has to be host-side MTU on critical-path ports.
3. **No 802.3az / EEE on the classic 3560G.** The hardware predates the standard (3560G ≈2007; 802.3az ratified 2010; EEE shows up on the later 3560-X / 3650 / 3850 refresh platforms). The `no energy-efficient-ethernet` command does not apply on this hardware — do not use it.
4. **RB3011 has two switch chips.** Ports ether1–5 on one QCA8337, ports ether6–10 on another; each chip has a 1 Gb/s link to one CPU core. **Cross-chip traffic and bridge VLAN filtering across chips fall back to CPU** [doc — help.mikrotik.com/docs/spaces/ROS/pages/15302988/Switch%20Chip%20Features; networkinghowtos.com/howto/fix-ethernet-port-flapping-on-mikrotik-rb3011/]. All bridged ports must live on the same switch chip.

### 3.4.1.2 Topology

```
             Institute / Building network (upstream)
                            │
                       (WAN)│ ether1
                            │
               ┌────────────▼────────────┐
               │   MikroTik RB3011UiAS    │    router + firewall + NTP + DHCP
               │   ether2 .. ether10      │    (chip1: 1–5; chip2: 6–10)
               └─┬─────────────────┬─────┘
          ether2│ (mgmt+L3)        │ ether3 (trunk; VLANs 10/20/30/40 only)
                │                  │
                │           ┌─────▼───────────────────────────┐
                │           │   Cisco Catalyst 3560G-48TS  (IP Base)  │
                │           │        32 Gbps non-blocking fabric        │
                │           └┬───┬───┬───┬───┬───┬───┬───┬───┬───┘
                │        Gi0/1   /2  /3  /4  /5  /6  /7  /8  /10..15
                │        trunk OPX QM-r (rsv) Tower Tower Elite Mini cams
                │              [VLAN 50: trust enclave]  bro ctl D    [V20]
                │                                        ker NIC
                │                                       [V50][V10][V10][V10]
            (mgmt console / OOB)
```

The critical-path L2 segment is **VLAN 50 only on the 3560G fabric**: OPX+ ↔ QM router LAN ↔ Z2 Tower broker NIC. **VLAN 50 is excluded from the trunk to the RB3011**; the RB3011 has no SVI for it. Other hosts that occasionally talk to OPX (dashboards reading status) cross one inter-VLAN L3 hop, which is fine for non-critical traffic but disallowed for the rearrangement loop.

### 3.4.1.3 VLAN plan

| VLAN | Name | Subnet | Members | Notes |
|---|---|---|---|---|
| 10 | `lab-core` | 10.10.10.0/24 | Z2 Tower control NIC, EliteDesk, Z2 Mini, ThinkCentre mgmt NIC, lab terminals | Control plane. Scheduler ↔ broker mgmt ↔ DB ↔ dashboards. |
| 20 | `instruments` | 10.10.20.0/24 | ProEM HS1024, 2× DMK 33GX545, 2× DMK 33GX264 | GigE cameras. Jumbo MTU only if measured-necessary (see §3.4.1.5). |
| 30 | `mgmt` | 10.10.30.0/24 | 3560G mgmt IP, RB3011 ether2 mgmt IP, IPMI/BMC if any | OOB switch & router admin; NTP server lives here. |
| 40 | `guest` | 10.10.40.0/24 | Off-lab laptops, analyst workstations | Read-only access to Postgres replica + data lake. No mutation. |
| **50** | **`opx-rt`** | **192.168.88.0/24** (QM router DHCP) | OPX+ controller(s), QM router, **Z2 Tower broker NIC** | **L2-only on the 3560G. No SVI on the RB3011. No firewall visibility.** Trust enclave: security via physical port assignment + host firewall + switch port config, **not** via RB3011 ACLs. |
| 60–99 | reserved | — | future | Reserve in switch config; do not provision. |

### 3.4.1.4 Port assignment on the 3560G

| Ports | Use | Mode | Notes |
|---|---|---|---|
| Gi0/1 | RB3011 ether3 trunk | trunk dot1q, allowed VLANs 10/20/30/40 | **VLAN 50 deliberately not in allowed-list** |
| Gi0/2–4 | OPX+ controller, secondary OPX (future), QM router LAN | access, VLAN 50 | PortFast, BPDU guard, flowcontrol receive off |
| Gi0/5 | Z2 Tower broker NIC | access, VLAN 50 | same hardening |
| Gi0/6 | Z2 Tower control NIC | access, VLAN 10 | PortFast, BPDU guard |
| Gi0/7 | EliteDesk | access, VLAN 10 | same |
| Gi0/8 | Z2 Mini | access, VLAN 10 | same |
| Gi0/9 | ThinkCentre mgmt | access, VLAN 10 | same |
| Gi0/10–15 | GigE cameras | access, VLAN 20 | PortFast, BPDU guard, flowcontrol default (revisit after measuring dropped frames) |
| Gi0/16–47 | reserved | shut | label and disable until needed |
| Gi0/48 | mgmt console laptop | access, VLAN 30 | direct switch admin |
| Te0/1–4 SFP | reserved | shut | future fiber / SFP uplink |

### 3.4.1.5 Default-off knobs (opt-in only after measurement)

Two features that v1 of this plan enabled by default but are **off** in v2 until baselined:

- **`mls qos`** — leave disabled until a baseline run shows contention-induced jitter on the OPX path. With OPX on its own VLAN and its own access ports, contention is unlikely. Misconfigured QoS reorders traffic and can make latency *worse* [doc — cisco.com/c/en/us/td/docs/switches/lan/catalyst3560/.../scg3560/swqos.html].
- **`system mtu jumbo 9000`** — leave disabled (MTU 1500) until cameras are tested and show packet loss at default MTU. Jumbo MTU on the 3560G is global; if enabled, host-side MTU on every critical-path port must be explicitly pinned to 1500 so the only large frames on the wire are camera→ThinkCentre.

### 3.4.1.6 Cisco 3560G configuration (v2 default-baseline)

```cisco
hostname lab-switch
!
! ---- Jumbo MTU: OFF by default. Enable only if cameras require it. ----
! system mtu jumbo 9000
!
! ---- QoS: OFF by default. Enable only after baselining shows need. ----
! mls qos
!
! ---- VLANs ----
vlan 10
 name lab-core
vlan 20
 name instruments
vlan 30
 name mgmt
vlan 40
 name guest
vlan 50
 name opx-rt
!
! ---- OPX critical-path ports ----
interface range GigabitEthernet0/2 - 5
 switchport mode access
 switchport access vlan 50
 spanning-tree portfast
 spanning-tree bpduguard enable
 no cdp enable
 no lldp transmit
 no lldp receive
 flowcontrol receive off
 storm-control broadcast level pps 1000
 storm-control multicast level pps 1000
 storm-control action shutdown
 ! No `no energy-efficient-ethernet` — unsupported on classic 3560G.
!
! ---- lab-core hosts (VLAN 10) ----
interface range GigabitEthernet0/6 - 9
 switchport mode access
 switchport access vlan 10
 spanning-tree portfast
 spanning-tree bpduguard enable
!
! ---- camera access ports (VLAN 20) ----
interface range GigabitEthernet0/10 - 15
 switchport mode access
 switchport access vlan 20
 spanning-tree portfast
 spanning-tree bpduguard enable
 storm-control broadcast level pps 1000
 ! Leave flowcontrol at default; revisit after measuring dropped frames.
!
! ---- trunk to RB3011: VLAN 50 EXCLUDED ----
interface GigabitEthernet0/1
 description uplink-to-rb3011
 switchport mode trunk
 switchport trunk encapsulation dot1q
 switchport trunk allowed vlan 10,20,30,40
 switchport trunk native vlan 999
 spanning-tree link-type point-to-point
!
! ---- mgmt SVI ----
interface Vlan30
 ip address 10.10.30.10 255.255.255.0
 no shutdown
ip default-gateway 10.10.30.1
!
! ---- NTP, SSH-only-on-mgmt, no http ----
ntp server 10.10.30.1
ntp source Vlan30
no ip http server
no ip http secure-server
ip ssh version 2
line vty 0 15
 access-class MGMT-ONLY in
 transport input ssh
ip access-list standard MGMT-ONLY
 permit 10.10.30.0 0.0.0.255
!
spanning-tree mode rapid-pvst
spanning-tree extend system-id
```

### 3.4.1.7 MikroTik RouterOS configuration (v2)

```bash
/system identity set name=lab-router

# All bridged ports MUST be on switch chip 1 (ether1-5) for hardware offload.
# ether1 = WAN, NOT in bridge
# ether2 = mgmt access (chip 1)
# ether3 = trunk to Cisco (chip 1)
# ether4-5 = reserve, same chip
# ether6-10 = DO NOT add to lab bridge (different chip; CPU-forwarded)

/interface bridge add name=br-lab vlan-filtering=yes
/interface bridge port
add bridge=br-lab interface=ether3 pvid=1
add bridge=br-lab interface=ether2 pvid=30

# After add, VERIFY hardware offload:
#   /interface bridge port print
# Every bridge port must show the "H" (hardware offload) flag.
# If "S" (software) appears: re-check link-speed parity on the chip and
# RouterOS version; fix before going to production.

# Keep all chip-1 ports at the same negotiated speed (mixed speeds on one
# QCA8337 cause port flapping per networkinghowtos.com).
/interface ethernet set ether2 auto-negotiation=yes
/interface ethernet set ether3 auto-negotiation=yes

# Bridge VLAN table
/interface bridge vlan
add bridge=br-lab vlan-ids=10 tagged=ether3,br-lab
add bridge=br-lab vlan-ids=20 tagged=ether3,br-lab
add bridge=br-lab vlan-ids=30 tagged=ether3,br-lab untagged=ether2
add bridge=br-lab vlan-ids=40 tagged=ether3,br-lab
# VLAN 50 deliberately NOT in this table — trust enclave on Cisco only.

# L3 SVIs on the router (no SVI for VLAN 50)
/interface vlan add interface=br-lab vlan-id=10 name=vlan-lab-core
/interface vlan add interface=br-lab vlan-id=20 name=vlan-instruments
/interface vlan add interface=br-lab vlan-id=30 name=vlan-mgmt
/interface vlan add interface=br-lab vlan-id=40 name=vlan-guest

/ip address
add address=10.10.10.1/24 interface=vlan-lab-core
add address=10.10.20.1/24 interface=vlan-instruments
add address=10.10.30.1/24 interface=vlan-mgmt
add address=10.10.40.1/24 interface=vlan-guest
add address=<institute>/24 interface=ether1
/ip route add gateway=<institute-gw>

# DHCP per VLAN (pull reservations from network/ip_reservations.yaml — §3.12)
/ip pool add name=lab-core-pool ranges=10.10.10.100-10.10.10.200
/ip dhcp-server add name=dhcp-lab interface=vlan-lab-core address-pool=lab-core-pool lease-time=8h
/ip dhcp-server network add address=10.10.10.0/24 gateway=10.10.10.1 dns-server=10.10.10.1
# repeat for VLAN 20 / 30 / 40

# Firewall — least privilege between VLANs
/ip firewall filter
add chain=forward action=accept connection-state=established,related
add chain=forward action=accept src-address=10.10.40.0/24 dst-address=10.10.10.20 dst-port=5432 protocol=tcp \
    comment="analysts -> Postgres on EliteDesk"
add chain=forward action=accept src-address=10.10.10.0/24 dst-address=10.10.20.0/24 \
    comment="lab-core -> instruments"
add chain=forward action=drop in-interface=vlan-guest
add chain=forward action=drop in-interface=vlan-instruments out-interface=vlan-lab-core

# NTP server (local stratum-2). All hosts sync to 10.10.30.1.
/system ntp client set enabled=yes servers=pool.ntp.org
/system ntp server set enabled=yes broadcast=no manycast=no multicast=no

# Lock down services
/ip service set telnet disabled=yes
/ip service set ftp disabled=yes
/ip service set api disabled=yes
/ip service set winbox address=10.10.30.0/24
/ip service set ssh address=10.10.30.0/24
```

### 3.4.1.8 Host-side notes

- **MTU pinning:** if `system mtu jumbo 9000` is later enabled on the switch for camera traffic, every host on VLAN 10 and VLAN 50 must explicitly set its NIC MTU to 1500 (Windows: `netsh interface ipv4 set subinterface "..." mtu=1500 store=persistent`). This prevents head-of-line blocking on the broker NIC port.
- **Z2 Tower dual-homing:** the broker NIC binds to VLAN 50 (192.168.88.x via QM-router DHCP); the control NIC binds to VLAN 10 (10.10.10.10 static). The broker process binds its `QuantumMachinesManager(host=...)` call to the VLAN-50 interface address explicitly.
- **Camera bring-up:** start cameras at MTU 1500 with default flow control. Measure `Statistic_Failed_Buffer_Count` (or vendor equivalent) per camera. Only enable jumbo and / or tune flow control after measurement [doc — docs.baslerweb.com/knowledge/how-to-troubleshoot-lost-packets-or-frames-while-using-gige-cameras; docs.baslerweb.com/network-related-parameters].

### 3.4.1.9 What this design eliminates and what it does not

| Source of jitter | Achievable on this gear? |
|---|---|
| 3560G switching fabric | sub-µs; nothing to do |
| RouterOS forwarding in OPX path | **eliminated by design**: VLAN 50 never traverses the RB3011 |
| Spanning-tree convergence on link flap | bounded to ~2 s via RPVST + PortFast |
| Broadcast / multicast storms | bounded via `storm-control` |
| Inter-VLAN L3 hop | not in critical path |
| EEE wake delays | not present (3560G has no EEE) |
| Host stack (Windows NDIS, GIL, kernel scheduler) | **NOT eliminable** — floor at ~10s of µs to ms; managed via process discipline in §3.2 |
| `insert_input_stream` server-side queueing | **NOT eliminable** — covered by verify-item #2 in §3.11 |
| Cross-host clock drift (NTP) | bounded to ~ms; sub-µs requires PTP hardware not present |
| TCP retransmits / RTO tails | reduce probability; not eliminate |

**The switch is not the jitter bottleneck on this gear.** The host stack and the QM server-side queue are. The acceptance tests in §3.11 measure the application layer, not the network layer, for this reason.

## 3.5 In-shot rearrangement feedback loop (Decision 2, detailed)

This is the latency-critical loop. Architecture:

```
[Atoms]
   ↓ optical
[Andor iXon EMCCD]
   ↓ CameraLink (Base/Full)
[BitFlow Axion 1xB] — PCIe Gen2 ×4, StreamSync DMA engine
   ↓ GPUDirect for Video  (P2P PCIe write, no CPU bounce)
[RTX 4000 Ada Generation, 20 GB] — PCIe Gen4 ×16
   ├─ CUDA kernel: site-classifier (matched filter / lightweight FFN)
   ├─ CUDA kernel: assignment (parallel multi-tweezer / Hungarian)
   └─ CUDA kernel: encode trajectory params
   ↓ cudaMemcpyAsync → pinned host memory  (~10 µs)
[Broker Python process on Z2 Tower]  — same process, same machine
   ↓ job.insert_input_stream("traj_params", arr)
[OPX server (TCP, lab subnet via QM router)]
   ↓
[OPX+ PPU input-stream FIFO]
   ↓ advance_input_stream()   ←  QUA blocks here for the next vector
[QUA program on PPU]
   ├─ unpack (src_x, src_y, tgt_x, tgt_y, t_ramp) tuples
   └─ play() chirped/Blackman AM·FM on AOD-X and AOD-Y channels
   ↓ analog out → RF amp → AOD
[Atoms rearranged]
```

Sources for the architecture:
- BitFlow Axion 1xB shares the Cyton-CXP backend: "StreamSync DMA engine and buffer manager. A brand new PCIe Gen 2 interface, with DMA optimized for modern (fully loaded, fully busy) computers" [doc — bitflow.com/products/camera-link/axion-1xb/].
- BitFlow markets GPUDirect for Video on these cards; NVIDIA's official partner page lists BitFlow as a supported framegrabber vendor for GPUDirect for Video [doc — bitflow.com/technology/support-for-gpu-direct-for-video/, developer.nvidia.com/gpudirectforvideo].
- RTX 4000 Ada Generation: GPUDirect for Video and GPUDirect RDMA are both listed on the OEM datasheets [doc — lenovopress.lenovo.com/lp2144-thinksystem-nvidia-rtx-4000-ada-20gb-pcie-active-gpu, pny.com/.../PNY-NVIDIA-RTX-4000-Ada-Generation-Datasheet.pdf]; NVIDIA's GPUDirect RDMA docs confirm Quadro-class support [doc — docs.nvidia.com/cuda/gpudirect-rdma/].
- QUA input streams: "Input streams are a queue data structure that allows passing data from the client computer to a running job in the OPX+ with minimal latency. … declare it in the QUA program using the `declare_input_stream()` command. … The variable/vector can then be used as a normal QUA variable." `advance_input_stream` blocks if no new data is available [doc — docs.quantum-machines.co/1.2.6/docs/Guides/features/, docs.quantum-machines.co/1.3.0/docs/API_references/qua/dsl_main/]. Python side: `insert_input_stream` via the Job API (QOP 2.0+) [doc — docs.quantum-machines.co/0.1/qm-qua-sdk/docs/API_references/qm_job_api/].
- QM OPX+ internal feedback latencies (PPU-local conditional logic): 224 ns conditional, 272 ns parametric [doc — quantum-machines.co/products/opx/]. These are *not* the external loop budget; they apply once data is already inside the PPU.
- Prior art for the in-QUA-trajectory variant: Saffman lab atom sorting [doc — github.com/qua-platform/qua-libs/.../AMO/Use Case 1 - Saffman Lab - Atom Sorting]. The 5 ms PC→PPU number in the QM cold-atoms whitepaper is for that variant (occupation-matrix push) [doc — quantum-machines.co/wp-content/uploads/2022/07/Use-Cases-Neutral-Atoms.pdf, cited from search metadata; PDF not parsed].
- The faster route via Hamamatsu Orca Quest 2 + Quantum Machines OP-NIC has been explicitly ruled out by the lab as not viable; the GPU-RDMA-into-input-stream pipeline above is the lowest-latency option achievable on the current hardware inventory.

**Latency budget for ~100-atom array (estimates, to be measured):**

| Stage | Best estimate | Source / basis |
|---|---|---|
| 1. Andor readout, 256×256 ROI | 0.5–2 ms | iXon Ultra datasheet; verify on the lab's EM-gain / vertical-shift settings |
| 2. Axion 1xB → GPU via GPUDirect for Video | 0.1–0.3 ms | 131 KB frame / PCIe Gen2 ×4 (≈2 GB/s) ≈ 65 µs payload + DMA setup; [doc — bitflow.com/products/camera-link/axion-1xb/, bitflow.com/technology/support-for-gpu-direct-for-video/] |
| 3. CUDA classifier kernel | 0.1–0.5 ms | matched-filter / FFN on RTX 4000 Ada is overprovisioned for 256×256 [doc — arxiv:2510.25982 abstract; arxiv:2603.03149 reports 115 µs for 256×256 on UltraScale+ FPGA, GPU is comparable] |
| 4. CUDA assignment kernel | 0.1–0.5 ms | Hungarian / parallel multi-tweezer for ~100 atoms [inference from PRApplied 19, 034048 and 2401.04893 abstracts] |
| 5. GPU → pinned host → Python pickup | 0.05–0.2 ms | `cudaMemcpyAsync` over PCIe Gen4; pinned-memory transfer; Python overhead trivial |
| 6. `insert_input_stream` → OPX server → PPU FIFO | **0.5–5 ms (unknown)** | QM docs say "minimal latency" but publish no number; the 5 ms QM whitepaper figure was for a ~100-trap *occupation-matrix* push (much larger payload than a few hundred bytes of trajectory params); **verify on the lab's cluster** |
| 7. `advance_input_stream` + AOD play setup | <0.05 ms | PPU clock-cycle scale [inference from QUA timing model] |
| 8. AOD chirp itself (Blackman AM + FM) | 1–5 ms | physics-limited; identical in any architecture [doc — QM cold-atoms whitepaper, cited from search metadata] |
| **Total loop, optimistic** | **~2–4 ms** | dominated by camera + network hop |
| **Total loop, pessimistic** | **~7–10 ms** | if `insert_input_stream` lands at the 5 ms QM-whitepaper ceiling for any payload size |

The chirp duration is physics, not architecture — do not expect to shrink it. The two terms that *can* shrink with engineering effort are stage 6 (the network hop) and stage 1 (camera readout, via smaller ROIs and faster EM-gain modes).

**Where the loop closes:** *the AOD waveform is generated inside the OPX+ PPU.* The PPU consumes a small array of trajectory parameters via `advance_input_stream` and converts them to a chirped Blackman pulse on the AOD channels. The trajectory *computation* lives on the Tower GPU; the *waveform synthesis* lives on the PPU. This split is the seam.

**Software contract** (the 5+ year seam):

```python
# QUA side — compiled once per device_descriptor snapshot
with program() as rearrange:
    n_moves = declare(int)
    params  = declare_input_stream(
        t=fixed, name="traj_params",
        size=N_MAX_MOVES * 5,   # 5 floats per move: (src_x, src_y, tgt_x, tgt_y, t_ramp)
    )
    assign(n_moves, IO1)                # set by Python before insert_input_stream
    advance_input_stream(params)        # blocks until Python pushes
    with for_(i, 0, i < n_moves, i + 1):
        # unpack five-tuple, call play() with AM/FM chirp on aod_x and aod_y
        ...

# Python side — in the broker process on the Tower
def rearrangement_shot(target_geometry):
    raw    = framegrabber.grab_into_gpu(gpu_buf)        # GPUDirect, ~200 µs
    occ    = classifier_kernel(raw)                      # ~300 µs
    moves  = assignment_kernel(occ, target_geometry)     # ~300 µs
    params = encode_trajectory(moves)                    # ~100 µs
    job.io1.set(len(moves))                              # tells QUA how many to read
    job.insert_input_stream("traj_params", params)       # ~ms; measure
    # PPU plays the AOD chirps; result arrives via stream_processing afterwards
```

The **contract that must survive 5+ years** is the shape of `traj_params`: a flat float array of `(src_x, src_y, tgt_x, tgt_y, t_ramp)` tuples and the QUA `input_stream` name. Everything above the contract (CUDA implementation, classifier model, assignment algorithm, lighter Andor frames) is rebuildable every 2–3 years. Everything below (QUA template, AOD waveform shapes) is rebuildable per QOP major version.

**Process discipline on the broker host** (see also §3.2):
- Broker process: single Python interpreter, RT priority, pinned CPU affinity.
- Framegrabber driver + CUDA pipeline run *in-process* in the broker. No IPC, no service boundary on the loop path.
- Andor camera driver is a separate Windows service for non-loop snaps; it is **not** in the loop path — the framegrabber DMA bypasses it.
- Compute service for non-loop GPU work runs in a separate process and **must not** be scheduled during a run (operator-visible mutex enforced by the scheduler on the EliteDesk).
- Data lake writer runs in a separate process and consumes shot results via shared-memory queue; asynchronous from the loop.

**Scaling to 1000 atoms:** the GPU compute scales gracefully — RTX 4000 Ada has substantial headroom for larger ROIs and bigger assignment problems. The dominant remaining concern is stage 6 (network hop). Options if it bites:
- Larger payload per push: send multiple sub-arrays in one `insert_input_stream` call; the QUA side reads multiple `advance_input_stream` cycles. (Same wire-transit; saves Python overhead.)
- Compress trajectory params before push (RLE on contiguous moves).
- If neither helps, the only remaining escape on the available hardware is to consolidate enough of the assignment logic into QUA that smaller param vectors suffice (essentially a hybrid of the Saffman in-QUA-trajectory approach for hot inner loops, with the GPU handling the assignment problem outline).

## 3.6 Calibration DAG: representation, persistence, edit rights, re-run triggers

**Representation.** Adopt the QUAlibrate / Optimus shape verbatim. A calibration node has:
- `name` (e.g. `single_qubit_pi_pulse_amplitude`)
- `inputs: list[str]` — registry parameter names it reads
- `outputs: list[str]` — registry parameter names it writes
- `qua_template` — the QUA program to run
- `analysis` — a Python function that consumes the QUA result and produces output values
- `max_age_s` — staleness threshold for downstream consumers
- `fitness_check` — a Python function that returns Pass / Marginal / Fail

A graph is just the topological closure of nodes whose outputs feed each other's inputs.

**Persistence.** Postgres. Three tables:
- `dag_nodes (name, inputs jsonb, outputs jsonb, qua_template_path, max_age_s, version)`
- `calibrations (id, dag_node_name, parent_id, generated_at, result_jsonb, fitness, run_uuid)`
- `registry (parameter, value_jsonb, calibration_id, valid_from, valid_until)`

Calibration IDs are monotone; rows are append-only. `registry` is a temporal view: "what was the value of `pi_pulse_amplitude` at time T" is a single point-query.

**Edit rights.** From §3.3: `senior_operator` can run a node (which writes new rows). `admin` can change `dag_nodes` (the recipe). No-one can change a historical `calibrations` or `registry` row — only insert new ones.

**Re-run triggers.** Three paths:
1. **Pull-based**: a `RunRequest.required_calibration` declares which params must be fresh, and the scheduler chains the DAG if `max_age_s` is exceeded.
2. **Push-based**: a fitness_check failure on a node automatically re-runs its node and downstream nodes.
3. **Scheduled**: a cron-shape rule re-runs node X every Y hours, regardless. (e.g. drift-prone parameters.)

This is the *Optimus* pattern (Kelly 2018) with the *QUAlibrate* implementation shape, persisted in Postgres so you don't lock yourself to QUAlibrate's private source [doc — github.com/qua-platform/qualibrate].

## 3.7 Mid-circuit measurement and conditional logic

Three architectural questions:

1. **Where is MCM physically expressed?** Inside the QUA program. The OPX+ PPU supports real-time classical calculations and decisions [doc — docs.quantum-machines.co/1.3.0/docs/Introduction/qua_overview/]. The conditional latency is 224 ns; the parametric latency is 272 ns [doc — quantum-machines.co/products/opx/]. This is fast enough for the analog and gate-model conditional flows you'll want at the tweezer scale.

2. **How is it expressed at the user level?** The Quantinuum MCMR-as-compiler-pass pattern transfers (P18). You write the experiment in terms of "atoms in three zones" (Bluvstein 2023 architecture, P11); the compiler at Layer 4 rewrites that into the appropriate QUA `if_ / for_ / measure / assign` constructs. The compiler is the only place that needs to know about MCM semantics; user code doesn't.

3. **What's the failure semantic?** If the QUA measurement yields a value outside the expected range, the QUA program *should* `pause` and surface a `RtJobResult.status="rt_error"` rather than guess. This costs a shot; it does not corrupt downstream calibrations.

## 3.8 Multi-user data provenance

The chain is:

```
code commit SHA  ─┐
                  ├─→ device_descriptor_id (versioned row)
                  ├─→ calibration_id (Optimus snapshot)
                  ├─→ qua_program_blob (config_hash)
                  ↓
                run_uuid
                  ↓
                shot_uuid (one per shot)
                  ├─→ shot HDF5 (embeds all of the above as attrs)
                  └─→ metadata DB row (same, indexed)
```

Every shot, every analysis output, every dashboard query points back through this chain to a single git commit + a single calibration ID + a single device descriptor ID. This is the **5-year-survival contract.** UIs, drivers, schedulers can be rebuilt; this chain cannot break.

Reference patterns: P5 + P6 + P19 + IBM `BackendProperties + calibration_id`; Cirq Quantum Engine per-job calibration retrieval [doc].

## 3.9 24-month build sequence with stop/reassess milestones

**Phase 0 (0–2 months) — Foundations**
- Move OPX broker from Z2 Tower to EliteDesk 800 G6. Verify with the qua-libs Saffman example before moving production code.
- Stand up PostgreSQL on EliteDesk; create `runs`, `shots`, `device_descriptors`, `calibrations`, `registry` tables. Schema only — no migration yet.
- Pin all NICs; jumbo frames on GigE cameras [doc — labscript Spinnaker / Pylon GigE notes recommend this]. Document VLAN reservation plan even if you don't activate.
- Set up NTP (`chronyd`/`w32time`) lab-wide.

**Milestone 0 (stop/reassess):** *Can we still run yesterday's experiment after the broker move?* If yes, go. If no, do not proceed to Phase 1 until the regression is gone.

**Phase 1 (2–6 months) — Compiler + descriptor**
- Define the `DeviceDescriptor` dataclass and a YAML serialization. Initial fields: AOD axes, RF amp ranges, camera ROIs, lattice spacing, timing budgets.
- Write the Layer 4 compiler: takes (`Template`, `parameters`, `descriptor`, `calibration_snapshot`) → (`QmConfig`, `qua_program`, `non_rt_plan`). Reject-at-submit on descriptor violation.
- Wrap one existing experiment template through the new compiler. Compare against a hand-written run as ground truth.
- Add HDF5-per-shot writes with embedded attrs (`shot_uuid`, `run_uuid`, `calibration_id`, `descriptor_id`).

**Milestone 1:** *One end-to-end run through Compiler → broker → OPX → HDF5 → DB, with provenance attrs and DB rows queryable.*

**Phase 2 (6–10 months) — Calibration DAG**
- Implement `DagNode`, `DagTraversal`. Persist to Postgres.
- Port 3–5 existing calibrations (e.g. pi-pulse amplitude, AOD frequency calibration, atom-detection threshold) as nodes. Drive them through the DAG runner.
- Wire `RunRequest.required_calibration` → DAG traversal → freshness check.
- Add fitness_check on each ported node.

**Milestone 2:** *Re-running a stale calibration is triggered by `RunRequest.required_calibration`, not by a postdoc remembering.*

**Phase 3 (10–14 months) — Rearrangement loop hardening**
- Move the classifier off the orchestrator process onto the Tower compute service. Make it a Python long-running daemon with a gRPC/HTTP interface.
- Measure latency budget §3.5 end-to-end. Compare against the qua-libs Saffman timing baseline.
- If <5 ms is hit, freeze the loop. If not, identify the dominant stage and decide whether to go the LLRS-style hardware route.

**Milestone 3:** *Stable rearrangement at the current array size with measured per-stage latencies in a dashboard.*

**Phase 4 (14–18 months) — Multi-user & access control**
- Implement the role × verb matrix in Postgres + scheduler.
- Add per-user audit log on every mutating verb.
- Off-lab read-only dashboard.

**Milestone 4:** *A wrong command from one operator cannot corrupt past shots or break the running calibration.*

**Phase 5 (18–24 months) — Scaling prep for 1000 atoms**
- Re-measure the rearrangement loop at the new array size.
- Evaluate GPU classifier replacements (matched filter, lightweight CNN) per arXiv:2510.25982 abstract direction.
- Decide on the framegrabber → FPGA → OPX path (LLRS-style) if Phase-3 budget is exceeded.
- Stress-test the calibration DAG with O(50) nodes and chained dependencies.

**Milestone 5:** *Rearrangement budget meets the target at scale, or a concrete plan to close the gap is in flight.*

**Stop/reassess discipline:** every milestone is a *real* stop. Do not start the next phase until the previous milestone's success metric is checked in writing into `outputs/<slug>.provenance.md` (or its successor file).

## 3.10 What must survive 5+ years vs what should be rebuildable

| Layer | Lifetime | Why |
|---|---|---|
| Shot metadata schema (`runs`, `shots`, `calibrations`, `registry`, `device_descriptors`) | **5+ years** | Provenance chain is the durable contract |
| Calibration DAG node interface (`inputs`, `outputs`, `analysis`, `fitness_check`) | **5+ years** | Optimus/QUAlibrate-shaped; field convergence | 
| HDF5 attribute names (`shot_uuid`, `run_uuid`, `calibration_id`, `code_commit_sha`, `descriptor_id`) | **5+ years** | Every analysis script will read these |
| `DeviceDescriptor` field semantics | **5+ years** (additive only) | Like Pasqal `Device`; new fields fine; renames forbidden |
| The `RtJobSubmission` / `RtJobResult` shape | **5+ years** | Layer 1↔2 contract |
| **Rearrangement trajectory-params contract** (`traj_params` shape + QUA `input_stream` name) | **5+ years** | The GPU↔PPU seam from §3.5. CUDA implementation changes; the contract does not |
| Role × verb matrix | **5+ years** (verbs can be added) | Security contract |
| Compiler internals (template→QUA) | 2–3 years | Will be rewritten when QM API changes (QOP 2.x→3.x, OPX+→OPX1000) |
| Scheduler internals | 2–3 years | Cron rules / DAG runner are common pattern; replaceable |
| GPU rearrangement pipeline (CUDA kernels, classifier model, assignment algorithm) | 2–3 years | Rebuildable as algorithms improve; contract above stays put |
| Specific drivers (Andor SDK, BitFlow SDK, NVIDIA driver) | as long as the hardware lives | One driver per instrument, replaceable when instrument is replaced |
| Dashboards & UIs | 2–3 years | Rebuildable; do not let UI churn back-propagate into the contract layers |
| Choice of QUAlibrate library | 1–2 years | Source is private; you may need to swap. The *DAG shape* survives; the library doesn't |
| Choice of Postgres vs SQLite vs SQL Server | 5+ years | Postgres for now; schema is portable |

This is the explicit answer to your "which seams must survive 5+ years" question.

---

# 5–10 specific things to verify, push back on, or stress-test

I am opinionated above. Here are the places where I want you to push back, and where I want to be wrong if I'm wrong.

1. **End-to-end loop latency on the Tower-resident broker.** With the broker, Andor, framegrabber, and CUDA pipeline all in-process on the Tower, measure (a) Andor frame readout, (b) Axion 1xB → GPU GPUDirect transfer, (c) classifier + assignment compute, (d) `insert_input_stream` round-trip, (e) total wall-clock from frame trigger to AOD chirp start. The §3.5 budget assumes ≈4 ms optimistic / ≈10 ms pessimistic; **the real number is unknown until measured.** Baseline comparison: the in-QUA-trajectory variant from the Saffman lab `qua-libs` example [doc — github.com/qua-platform/qua-libs/.../AMO/Use Case 1].

2. **`insert_input_stream` payload-size scaling.** QM says "minimal latency" without publishing a number; the only quantitative figure ("<5 ms for ~100 traps") is from the cold-atoms whitepaper and refers to occupation-matrix pushes [doc — quantum-machines.co/wp-content/uploads/2022/07/Use-Cases-Neutral-Atoms.pdf, cited from search metadata; PDF not parsed]. **Independently measure** `insert_input_stream` latency on the cluster across realistic trajectory-param payload sizes (16 B, 256 B, 1 KB, 8 KB). If the curve is flat at ≈1 ms regardless of payload, the loop budget closes. If it scales linearly past 5 ms, stage 6 in §3.5 will dominate.

3. **QUAlibrate dependency risk.** QUAlibrate source moved to a private repo [doc — github.com/qua-platform/qualibrate]. **Verify** you have a written commitment from QM about access / pricing / sunset timelines *before* making it load-bearing. If access is conditional, decouple early — build to the *interface* (your `DagNode` dataclass), not to the library.

4. **labscript-Issue-#112-style timing-bottleneck risk in your setup.** Inventory every clocked device: which is the slowest? In a labscript world this would lock your cadence. Under the proposed architecture, the OPX+ owns the clock so this shouldn't bite — but **verify** that no GigE camera ROI / SLM HDMI frame interacts with the QUA timing such that a slow device implicitly clocks the experiment.

5. **SLM HDMI 30 Hz / 16.7 ms transfer.** You stated this. It puts a hard floor on any experiment that needs to *update* the hologram between shots. **Verify** which experiment templates this constrains, and whether they're in your 24-month plan.

6. **Time-sync claim.** I argued NTP is enough. **Verify** by measuring drift between hosts after 24 h. If it exceeds 100 ms regularly, you may need a local NTP server with a GPS-disciplined source or a chronyd configuration tighter than the institute pool default. [doc — alliedtelesis PTP guide for context on when PTP becomes load-bearing].

7. **Single OPX+ vs cluster.** I have written the proposal assuming one OPX+. If you will add a second OPX+ before the 24-month mark, the QM cluster docs [doc — docs.quantum-machines.co/.../OPX+_installation/] describe the topology — but verify whether the "main OPX+ + secondary OPX+" sync model places any new constraint on the QM-router subnet design in §3.2.

8. **Atom Computing's "real-time conditional branching" capability.** I cited it from atom-computing.com/ac1000/ as documented. That is the *capability target*, not a recipe — verify that what you mean by "MCM + conditional logic in QUA" is at parity. If not, what's the delta?

9. **The 5-year schema commitments.** I'm asking you to commit to HDF5 attribute names and DB column names for 5+ years. **Stress-test** this by walking the current data through a hypothetical 5-year audit: can a future postdoc reproduce shot N exactly from the chain (commit SHA, descriptor_id, calibration_id)? If any link is weak, fix it before Phase 1 ends.

10. **Conway's Law sanity check.** The proposed architecture has six layers; your team has 8 users + automated jobs. **Verify** that no layer is "owned by one person" — every layer should have at least two operators who can debug it. If it doesn't, you are setting up a Conway's-Law-shaped fragility (A20) [doc — melconway.com/research/committees.html].

## Network-layer acceptance tests (added in R2; replace any ICMP-based jitter target)

11. **OPX command-latency baseline.** Measured *inside QUA* with `get_timestamp()` / PPU clock counters across ≥10⁵ `insert_input_stream → advance_input_stream` round-trips. Report median, p95, p99, max. This is the only authoritative latency number for the rearrangement loop. Host-side ICMP / ping numbers are scheduler-bound on Windows and not informative — do not use them as the acceptance criterion.

12. **Dropped camera frames under load.** Per camera, over a 30-minute run: `Statistic_Failed_Buffer_Count` (Basler Pylon Viewer) or vendor-equivalent counter at zero. If non-zero, investigate camera-side mitigations first (Inter-Packet Delay, NIC receive buffer, dedicated NIC, Performance Driver) before touching switch flow control [doc — docs.baslerweb.com/knowledge/how-to-troubleshoot-lost-packets-or-frames-while-using-gige-cameras].

13. **DB / dashboard isolation under load.** Measure verify-item-11 numbers *while* a stress-load runs on Postgres (`pgbench`) on the EliteDesk and the dashboard polls at full rate. **Goal: < 5 % degradation vs idle baseline.** If this fails, the VLAN separation or QoS policy needs revisiting.

14. **Switch / router correctness checks.** Run after every config change and quarterly:
    - `show interfaces Gi0/x counters errors` on every critical port — non-zero CRC / align / giants / runts / input-errors flags a hardware/cable problem (not a config one).
    - `show mls qos interface Gi0/x statistics` *iff* QoS later enabled — confirm the priority queue is non-zero on the OPX path.
    - `/interface bridge port print` on the RB3011 — every bridge port must show the `H` (hardware offload) flag. Any `S` means CPU forwarding and must be fixed.
    - `ping -M do -s 8972` end-to-end on VLAN 20 — succeeds iff jumbo is end-to-end (only matters if jumbo was opted in per §3.4.1.5).
    - `w32tm /query /status` (Windows) / `chronyc tracking` (Linux) on every host — sustained NTP offset < 10 ms.

---

# 3.12 Operational recovery (added in R2)

The network design in §3.4.1 is fast and clean only if the lab can also recover from common failures within bounded time. This section codifies the operational layer.

### 3.12.1 Static IP reservation table

Authoritative source: `network/ip_reservations.yaml` in the lab repo. The RB3011 DHCP server pulls reservations from it via `/ip dhcp-server lease add ... make-static`.

| VLAN | Host / device | IP | Notes |
|---|---|---|---|
| 10 | Z2 Tower control NIC | 10.10.10.10 | broker control plane |
| 10 | EliteDesk | 10.10.10.20 | scheduler + Postgres |
| 10 | Z2 Mini | 10.10.10.30 | SLM host |
| 10 | ThinkCentre mgmt NIC | 10.10.10.40 | slow-camera host |
| 20 | ProEM HS1024 | 10.10.20.10 | GigE |
| 20 | DMK 33GX545 #1 / #2 | 10.10.20.11 / 12 | GigE |
| 20 | DMK 33GX264 #1 / #2 | 10.10.20.13 / 14 | GigE |
| 30 | 3560G mgmt | 10.10.30.10 | switch admin |
| 30 | RB3011 ether2 mgmt | 10.10.30.1 | router admin / NTP / gateway |
| 50 | OPX+ controller(s) | per QM router DHCP (192.168.88.x) | trust enclave |
| 50 | Z2 Tower broker NIC | per QM router DHCP | trust enclave |
| 50 | QM router | 192.168.88.1 | discovery + admin panel |

MAC addresses populated at deployment; cell left empty in this template.

### 3.12.2 Backup and restore

- **Switch config:** nightly `copy running-config tftp://10.10.30.20/lab-switch-YYYYMMDD.cfg` cron'd to a tiny TFTP server on the EliteDesk. Retain 30 days. Diff against previous night; alert on drift.
- **Router config:** nightly `/export file=lab-router-YYYYMMDD` cron'd; pulled by EliteDesk via SCP. Retain 30 days.
- **Both configs in git** under `network/` directory of the lab repo; committed manually on every intentional change with a message explaining the change.
- **Restore procedure** documented at `network/RESTORE.md` with literal commands and rollback steps for each device.
- **Test restore** quarterly: wipe a non-critical port config, restore from last night's backup, verify recovery; record elapsed time.

### 3.12.3 Physical layer

- **Label every patch cable** at both ends: `source-port → destination-port` (e.g., `tower-eth0 → switch-Gi0/6`). Re-label after any move.
- **Label every switch port** on the front panel with VLAN ID + role (`V10 lab-core`, `V50 opx-rt`, etc.).
- **Spare 3560G** (or equivalent) in storage. If unobtainable, document the named replacement SKU and lead time (a Catalyst 3650 would add PTP, a future-proof upgrade).
- **Cable spares:** at least one labeled 50 cm Cat6 cable per port type in a labeled drawer; one spare power cord per device.

### 3.12.4 NTP fallback

- Primary: RB3011 (stratum 2; peers upstream to institute NTP or `pool.ntp.org`).
- Secondary: each host carries a hard-coded list of public NTP servers in its `w32tm` (Windows) or `chronyd` (Linux) config, documented at `network/ntp_fallback.md`.
- Verify with `w32tm /query /status` / `chronyc tracking` on every host weekly.

### 3.12.5 QM router replacement procedure

- Document literally how the QM router is connected: which switch port, DHCP scope (192.168.88.0/24), firmware version, factory-default password change record. Store at `network/qm_router.md`.
- Keep the QM router serial number, model, and support-contract details next to the device.
- **If QM router fails:** contact QM support. Do *not* attempt bypass without QM confirmation — the bypass may break OPX discovery / DHCP / firmware-update workflows in non-obvious ways. The OPX cluster is offline until QM advises or a spare router arrives.

### 3.12.6 Known-good minimal OPX network recipe

One-page cold-bring-up procedure to verify the OPX path is alive when everything else may be broken. Store at `network/MINIMAL_OPX.md`. Practice every 6 months as a fire drill.

```
1. Power on: 3560G, QM router, OPX+ controller, Z2 Tower.
2. Cable: Tower broker NIC → Gi0/5 (VLAN 50).
         OPX+ controller → Gi0/2 (VLAN 50).
         QM router LAN → Gi0/3 (VLAN 50).
3. Confirm 3560G has loaded its minimal config (or, from factory default,
   apply only the VLAN 50 subset of §3.4.1.6 — about 30 lines).
4. From Tower broker NIC, ping the QM router at 192.168.88.1.
5. If ping succeeds, run from Tower:
     python -c "from qm import QuantumMachinesManager; \
                qmm = QuantumMachinesManager(host='<OPX-IP>'); \
                print(qmm.version())"
6. If that succeeds, the OPX path is alive.
   Defer all other recovery (RB3011, other VLANs, dashboards) until
   step 5 succeeds.
```

### 3.12.7 Deployment acceptance criteria

The §3.4.1 network architecture moves from *proposed* to *deployed* only when **all** of the following hold:

- Acceptance tests §3.11 items 11–14 pass.
- A successful "known-good minimal OPX network" cold-bring-up (§3.12.6) has been demonstrated by **two different operators**, on different days.
- Restore-from-backup (§3.12.2) demonstrated end-to-end — wipe a port config, restore from last night's backup, verify recovery time recorded.
- Every IP in §3.12.1 is live and reachable from its expected VLAN, with cross-VLAN access strictly matching the firewall matrix in §3.4.1.7.
- Physical labels (§3.12.3) installed on every port and cable.

---

# Open questions (where public information ran out)

1. *Exact QUA stream-processing latency profile vs payload size.* QM docs describe the pipeline qualitatively [doc — docs.quantum-machines.co/1.3.0/docs/Guides/stream_proc/]; we don't have published end-to-end latency curves. **Measure on your cluster.**
2. *Atom Computing's experiment description language and calibration internals.* Public material is limited to the AC1000 capability list. We don't know the DSL or DAG shape.
3. *QuEra's internal calibration cadence.* The published architecture is Bluvstein 2023's three-zone layout; the cadence inside it is not public.
4. *Pasqal Fresnel internal RT layer.* Pulser is the user surface; what runs inside the box is not public.
5. *Klimov 2024 implementation details below the abstract.* PDF parsing was not performed per the workflow rule; the 3.7× error reduction is accepted as a published claim, not independently verified.
6. *QUAlibrate's pricing/access path now that it is private-source.* You will need to ask QM directly.

---

# Sources

Primary HTML sources used. PDFs cited only by URL where the search-metadata snippet was sufficient.

**ARTIQ / Sinara**
- https://m-labs.hk/artiq/manual/{introduction,getting_started_core,core_device,using_data_interfaces,management_system,main_frontend_tools,using_drtio_subkernels}.html
- https://m-labs.hk/artiq/manual-beta/rtio.html
- https://m-labs.hk/artiq/manual-legacy/releases.html
- https://github.com/m-labs/artiq/{wiki/DRTIO, issues/1345}
- https://github.com/sinara-hw/meta/wiki/{Home, uTCA}
- https://sayma-metlino-documentation.readthedocs.io/en/latest/wiki_introduction.html

**labscript-suite**
- https://labscriptsuite.org/en/stable/
- https://docs.labscriptsuite.org/projects/labscript/en/stable/connection_table/
- https://docs.labscriptsuite.org/projects/labscript/en/stable/api/_autosummary/labscript.base.Device/
- https://docs.labscriptsuite.org/projects/labscript/en/latest/api/_autosummary/labscript.core.IntermediateDevice/
- https://docs.labscriptsuite.org/projects/blacs/en/latest/components/
- https://docs.labscriptsuite.org/projects/blacs/en/latest/shot-management/
- https://docs.labscriptsuite.org/projects/runmanager/en/stable/usage/
- https://docs.labscriptsuite.org/projects/lyse/en/latest/introduction/
- https://docs.labscriptsuite.org/projects/labscript-utils/en/latest/api/_autosummary/labscript_utils.connections.ConnectionTable/
- https://docs.labscriptsuite.org/projects/labscript-devices/en/latest/{adding_devices,ex_conn_tables,devices/spinnaker,devices/pylon}/
- https://docs.labscriptsuite.org/en/latest/hardware/
- https://github.com/labscript-suite/labscript/issues/{18,112}
- https://pypi.org/project/labscript-suite/
- https://ar5iv.labs.arxiv.org/html/1303.0080 (Starkman et al. 2013)

**Quantum Machines / QUA / QUAlibrate**
- https://docs.quantum-machines.co/{1.2.0,1.2.3,1.2.4,1.3.0}/docs/Introduction/{qop_overview,qua_overview}/
- https://docs.quantum-machines.co/1.3.0/docs/Hardware/network_and_router/
- https://docs.quantum-machines.co/{1.2.3,1.3.0}/docs/Hardware/opx+installation/
- https://docs.quantum-machines.co/1.2.0/docs/Hardware/OPX1000_installation/
- https://docs.quantum-machines.co/1.3.0/docs/API_references/{qm_manager_api,qm_api,qm_opx1000_job_api}/
- https://docs.quantum-machines.co/{1.1.5,1.2.0,1.3.0}/docs/Guides/stream_proc/ (also `/qm-qua-sdk/docs/Guides/stream_proc/`)
- https://docs.quantum-machines.co/1.3.0/docs/API_references/qua/result_stream/
- https://www.quantum-machines.co/products/{opx,qua-universal-quantum-language}/
- https://www.quantum-machines.co/technology/pulse-processing-unit/
- https://www.quantum-machines.co/wp-content/uploads/2022/07/Use-Cases-Neutral-Atoms.pdf (cited from search metadata; PDF not parsed)
- https://qualibrate-docs.quantum-machines.co/
- https://qualibrate-docs.quantum-machines.co/{calibration_graphs,calibration_nodes,advanced_calibration_graphs}/
- https://github.com/qua-platform/{qualibrate,qualibrate-core,qua-libs}
- https://github.com/qua-platform/qua-libs/tree/main/Quantum-Control-Applications/AMO/Use%20Case%201%20-%20Saffman%20Lab%20-%20Atom%20Sorting

**QuEra / Aquila / Bloqade**
- https://bloqade.quera.com/dev/analog/
- https://bloqade.quera.com/dev/{background,analog/home/background}/
- https://bloqade.quera.com/v0.30.0/analog/contributing/design-philosophy-and-architecture/
- https://github.com/QuEraComputing/bloqade-analog/blob/main/docs/home/background.md
- https://arxiv.org/abs/2306.11727 (Aquila 1.0 whitepaper, abstract only)
- https://www.quera.com/blog-posts/insights-from-the-quantum-era---june-2023
- https://quera-c87685.webflow.io/aquila
- https://www.nature.com/articles/s41586-023-06927-3 (Bluvstein 2023; HTML abstract)
- https://pmc.ncbi.nlm.nih.gov/articles/PMC10830422/ (Bluvstein 2023 PMC mirror)
- https://arxiv.org/abs/2312.03982 (Bluvstein 2023 abstract)

**Pasqal / Pulser / Fresnel**
- https://docs.pasqal.com/pulser/{programming,hardware,sequence,register}/
- https://docs.pasqal.com/pulser/apidoc/_autosummary/{pulser.devices.Device,pulser.sequence.Sequence}/
- https://docs.pasqal.com/cloud/{first-job,fresnel-job,batches,sequence,pasqal-cloud/usage/advanced_usage}/
- https://docs.pasqal.com/cloud/api/core/operations/get_queue_api_v1_devices__dt_name__queue_get/
- https://github.com/pasqal-io/pulser

**Atom Computing**
- https://atom-computing.com/ac1000/
- https://builtin.com/job/senior-software-engineer-control-systems/8421921
- https://arstechnica.com/science/2023/10/atom-computing-is-the-first-to-announce-a-1000-qubit-quantum-computer/
- https://thequantuminsider.com/2022/05/20/atom-computing-researchers-keep-qubits-in-coherence-for-record-time/
- https://preview-www.nature.com/articles/s41586-024-08005-8 (Sr-88 MCM in clock qubits)
- https://arxiv.org/abs/2402.16220 (Sr-88 MCM, abstract only)
- https://arxiv.org/html/2411.11822v2 (Yb-171 24 logical qubits, HTML)
- https://arxiv.org/abs/2408.08288 (universal Yb computer, abstract only)
- https://www.eenewseurope.com/en/atom-shows-record-24-logical-qubit-quantum-computer/
- https://techcrunch.com/2024/11/19/microsoft-and-atom-computing-will-launch-a-commercial-quantum-computer-in-2025/
- https://thequantuminsider.com/2024/11/19/in-step-toward-scientific-advantage-microsoft-and-atom-computing-announce-the-launch-of-quantum-machine-with-record-breaking-logical-qubits/
- https://www.geekwire.com/2024/microsoft-atom-computing-quantum-logical-qubits/
- https://arstechnica.com/science/2024/11/how-to-fix-quantum-computing-errors-neutral-atom-edition/

**Quantinuum H-series**
- https://docs.quantinuum.com/systems/user_guide/hardware_user_guide/{h2,operation,access,workflow}.html
- https://docs.quantinuum.com/systems/trainings/h2/getting_started/mcmr.html
- https://docs.quantinuum.com/systems/data_sheets/Quantinuum%20H2%20Product%20Data%20Sheet.pdf (cited from search metadata; PDF not parsed)
- https://www.quantinuum.com/blog/{quantinuum-launches-the-most-benchmarked-quantum-computer-in-the-world-and-publishes-all-the-data, features-and-benefits-how-we-equip-our-users-to-unlock-the-full-potential-of-h-series-quantum-computers}
- https://physics.aps.org/articles/v16/209

**IBM Qiskit Runtime**
- https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/{runtime-service,ibm-backend}
- https://quantum.cloud.ibm.com/docs/en/guides/primitives
- https://quantum.cloud.ibm.com/docs/guides/run-jobs-session
- https://quantum.cloud.ibm.com/docs/en/api/qiskit-runtime-rest
- https://docs.quantum.ibm.com/run/get-backend-information
- https://github.com/Qiskit/qiskit-ibm-runtime/blob/main/qiskit_ibm_runtime/models/backend_properties.py
- https://qiskit.org/ecosystem/ibm-runtime/stubs/qiskit_ibm_runtime.options.Options.transpilation.html
- https://qiskit.github.io/qiskit-ibm-runtime/stubs/qiskit_ibm_runtime.IBMBackend.html

**Google calibration graph (Optimus)**
- https://arxiv.org/abs/1803.03226 (Kelly et al. 2018; abstract only)
- https://research.google/pubs/physical-qubit-calibration-on-a-directed-acyclic-graph/
- https://ar5iv.labs.arxiv.org/html/1910.11333 (Sycamore supplement HTML mirror — §VI.1.2 and FIG. S10)
- https://arxiv.org/abs/2308.02321 (Klimov et al. 2024; abstract only)
- https://research.google/pubs/optimizing-quantum-gates-towards-the-scale-of-logical-qubits/
- https://arxiv.org/abs/2006.04594 (Snake Optimizer; abstract only)
- https://quantumai.google/cirq/google/calibration
- https://quantumai.google/cirq/noise/qcvv/{isolated_xeb,parallel_xeb,xeb_theory,coherent_vs_incoherent_xeb}

**AMO control system primary literature & open-source reference stacks**
- https://arxiv.org/abs/2504.06528 (LLRS / low-latency feedback; abstract only)
- https://github.com/TQT-RAAQS/LLRS
- https://arxiv.org/abs/2411.12401 (Zynq RFSoC FPGA rearrangement; abstract only)
- https://arxiv.org/abs/2603.03149 (FPGA atom-detection 115 µs; HTML)
- https://arxiv.org/abs/2510.25982 (matched-filter / feedforward classifier review; HTML)
- https://arxiv.org/abs/2604.04600 (WPGS SLM holography; HTML)
- https://scipost.org/SciPostPhys.19.4.118 (Schreck group; SLM parallel rearrangement)
- https://arxiv.org/abs/2501.01391 (SLM parallel rearrangement; HTML)
- https://arxiv.org/abs/2510.11451 (3D AODL; HTML)
- https://arxiv.org/abs/2408.13652 (Customizable modular control for ultracold; HTML)
- https://arxiv.org/abs/2406.17603 (Microcontroller-based AMO timing; HTML)
- https://ar5iv.labs.arxiv.org/html/1901.04851 (Scalable hardware/software control for hybrid quantum systems)
- https://github.com/{DeMarcoAMO/Entangleware, ColdMatter/pycaf, sidwright8/SidEDMSuite, lazyoracle/nucleo-expt}
- https://www.science.org/doi/10.1126/science.aah3778 (Barredo 2016 abstract)
- https://journals.aps.org/prapplied/abstract/10.1103/PhysRevApplied.19.034048 (Parallel multitweezer assembly)
- https://hal.science/hal-03063905v1/file/2020_Schymik_PhysRevA.102.063107.pdf (Schymik 2020; PDF not parsed)
- https://browse.arxiv.org/html/2401.04893v1 (ML-enhanced tweezer rearrangement; HTML)
- https://www.nature.com/articles/s41467-022-29977-z (Norcia 2022 Phoenix; HTML abstract)
- https://journals.aps.org/prx/abstract/10.1103/PhysRevX.13.041051 (Graham 2023, single-species MCM; abstract)
- https://arxiv.org/abs/2112.14589 (Wisconsin programmable neutral-atom quantum computer; abstract only)

**Provenance & metadata patterns**
- https://docs.dataqruiser.com/qdrive_dataset.html
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11442463/ (QubiCSV / Sci Reports)
- https://preview-www.nature.com/articles/s41598-024-72584-9
- https://pypi.org/project/devqubit/
- https://github.com/csnp/qbom
- https://docs.influxdata.com/influxdb3/clustered/reference/internals/storage-engine/
- https://h5rdmtoolbox.readthedocs.io/en/v1.3.0/practical_examples/metadata4ing.html
- https://github.com/{TheresiaQuintes/specatalog, DeepLearnPhysics/spine-db}

**General SWE references**
- http://melconway.com/research/committees.html (Conway 1968)
- https://en.wikipedia.org/wiki/Conway%27s_law
- https://sph.sh/en/posts/bus-factor-knowledge-management-engineering-teams/
- https://repository.bilkent.edu.tr/server/api/core/bitstreams/4859b524-07f8-4a87-813a-b800f909e3b9/content (bus factor multimodal estimation)

**Time sync references**
- https://www.alliedtelesis.com/sites/default/files/ptp_feature_overview_guide_rev_a.pdf (cited from search metadata)
- https://www.mdpi.com/1424-8220/26/8/2519

**Network gear: MikroTik RB3011UiAS-RM (R2)**
- https://mikrotik.com/product/RB3011UiAS-RM
- https://help.mikrotik.com/docs/spaces/UM/pages/19136516/RB3011UiAS-RM
- https://help.mikrotik.com/docs/spaces/ROS/pages/15302988/Switch%20Chip%20Features
- https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge%2BVLAN%2BTable
- https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN
- https://help.mikrotik.com/docs/display/ros/basic+vlan+switching
- https://mikrotikdocs.fyi/ip/firewall/queues/{queue-tree,priority-queuing,queue-types}/
- https://www.networkinghowtos.com/howto/fix-ethernet-port-flapping-on-mikrotik-rb3011/
- https://forum.mikrotik.com/viewtopic.php?t=138340
- https://mum.mikrotik.com/presentations/IT14/starnowski.pdf

**Network gear: Cisco Catalyst WS-C3560G-48TS-S (R2)**
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3560/software/release/15-0_1_se/configuration/guide/scg3560/swqos.html
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3560/software/release/15-0_2_se/configuration/guide/scg3560/swintro.html
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3560/software/release/15-0_2_se/configuration/guide/scg3560/swiprout.html
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3560/hardware/installation/guide/3560hig/hgspecs.pdf
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3750/software/release/12-2_50_se/release/notes/OL18263.html (release notes scope)
- https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/214946-recommended-releases-for-catalyst-2960-3.html
- https://www.cisco.com/web/ANZ/cpp/refguide/hview/switch/3560.html
- https://ciscocity.com/cmsfiles/mainportal/shop/files/3560%20Datasheet.pdf (cited from metadata)
- https://hcl.ucd.ie/wiki/images/7/7d/Cisco3560Specs.pdf
- https://www.ds3comunicaciones.com/cisco/files/catalyst_3560.pdf
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3750x_3560x/software/release/15-2_4_e/configurationguide/b_1524e_consolidated_3750x_3560x_cg/b_1524e_consolidated_3750x_3560x_cg_chapter_010000.html (3560-X system MTU; later platform)
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3650/software/release/37e/consolidated_guide/b_37e_consolidated_3650_cg/configuring_system_mtu.html (3650 system MTU; later platform)
- https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3650/software/release/16-12/configuration_guide/lyr2/b_1612_lyr2_3650_cg/configuring_precision_time_protocol__ptp_.html (PTP on 3650/3850; proves NOT on 3560)
- https://www.cisco.com/c/en/us/support/docs/quality-of-service-qos/qos-packet-marking/13747-wantqos.html
- https://networkengineering.stackexchange.com/questions/2779/cisco-3560g-mtu-options
- https://music.manualsonline.com/manuals/mfg/cisco_systems/3560_6.html?p=332
- https://music.manualsonline.com/manuals/mfg/cisco_systems/3560_6.html?p=765
- https://www.manualowl.com/m/Cisco/WS-C3560G-48TS-S/Manual/288477?page=237
- https://web.fe.up.pt/~jruela/DOC/3560sg.pdf
- https://stack-systems.com/switch-cisco-ws-c3560g-48ts-s.html

**GigE Vision tuning (R2)**
- https://www.baslerweb.com/en/learning/tutorial-gige-vision-systems/
- https://docs.baslerweb.com/network-configuration-%28gige-cameras%29
- https://docs.baslerweb.com/knowledge/how-to-troubleshoot-lost-packets-or-frames-while-using-gige-cameras
- https://docs.baslerweb.com/network-related-parameters
- https://docs.baslerweb.com/network-bandwidth-control-%28blaze%29
- https://assets-ctf.baslerweb.com/dg51pdwahxgw/2cevzPRHqqWzf1tiQh6rgn/e562d5084d6fd699c077ec45c27497d3/AW00144501000_GigE_Vision_Network_Drivers_and_Bandwidth_Management.pdf (cited from metadata)
- https://www.cisco.com/c/en/us/td/docs/solutions/Verticals/Industrial_Automation/IA_Horizontal/Machine-Vision/IA-machine-vision-DIG.html
- https://nstx.pppl.gov/nstxhome/DragNDrop/Operations/Diagnostics_&_Support_Sys/D1CCD/GigE_Vision_for_Realtime_MV_11052010.pdf (cited from metadata)
- https://www.jai.com/downloads/technical-notes-how-to-use-packet-size-and-packet-delay

---

*End of draft. Last revision: R2 (2026-05-24, network architecture + operational recovery added per critique).*