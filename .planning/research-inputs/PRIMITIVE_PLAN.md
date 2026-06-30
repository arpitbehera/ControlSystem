Based on your summary, I would rebuild this as a control platform, not as a federation of cooperating Python scripts.

The current system already contains the right instincts: vendor SDKs are isolated into separate processes, OPX owns the deterministic timing, and image analysis is treated as part of the experiment loop. The problem is that those boundaries are incidental rather than enforced. Control flow, device access, GUI behavior, analysis, and persistence all leak across one another, so small defects turn into system fragility.

The redesign I would aim for is a **modular monolith at the codebase level, with a small number of supervised processes at runtime**. That gives you strong shared abstractions and testability without turning the lab stack into an ops-heavy microservice system.

## The architecture I would build

I would split the system into a **control plane** and a **data plane**.

The control plane owns run lifecycle, configuration, validation, health, persistence, and operator interaction.
The data plane owns high-volume frame movement and analysis.

A clean version looks like this:

```text
Operator UI / CLI
        |
        v
 Run Orchestrator / API  <---->  Config + Run Store
        |   \
        |    \----> Analysis Workers
        |
        +----> Device Services
                 - OPX service
                 - Picam service
                 - Pixelfly service
                 - Lock service
                 - SLM service

Camera services ---> Shared-memory frame buffer ---> Analysis / UI / Archiver
```

### Four design rules

1. **Python is never in the hard-timing loop.**
   OPX remains the timing authority. Python prepares, validates, arms, triggers, observes, and records.

2. **Each stateful resource has one owner.**
   A camera service owns camera state. The orchestrator owns run state. The UI owns no hardware state.

3. **Every cross-process boundary is typed and versioned.**
   No pickled dicts or objects over raw sockets.

4. **A run is an immutable snapshot.**
   Once a run starts, it executes against a frozen config/calibration/parameter bundle.

## Component boundaries and responsibilities

### 1) Supervisor

This replaces `Start_all_servers.py` as a real process supervisor.

Its job is to start services with explicit dependency order, enforce working directories, run readiness probes, restart failed workers when safe, and produce a startup health summary. It should know which services are core and which are optional.

In the current system, spawning bare scripts and hoping ports become available is not orchestration. It is process launching.

### 2) Run orchestrator

This is the heart of the system. It is the only component allowed to start or stop runs.

Responsibilities:

* Validate a run request against typed schemas
* Determine required versus optional devices
* Freeze a config/calibration snapshot
* Ask device services to configure and arm
* Compile or request compilation of the OPX program
* Start execution
* Coordinate shot acquisition, analysis, and persistence
* Emit progress/state events
* Handle failure, cancellation, and cleanup

This is also where the current script templates really belong. Instead of V1 and V2 templates, I would define a single stable experiment interface, something conceptually like:

* parameter schema
* required capabilities
* sequence builder
* acquisition contract
* analysis pipeline
* result reducer

That turns “script execution” into a formal platform concept.

### 3) Experiment definitions

`BenchmarkV2` should not be a giant method that mixes defaults, GUI, camera prep, sequence generation, download logic, stats, and persistence.

I would split experiment logic into small, pure components:

* `ExperimentDefinition`
* `RunRequest`
* `RunPlan`
* `ShotPlan`
* `ShotResult`
* `RunSummary`

For example, the benchmark cases become separate plan builders rather than branches inside one `run()` method:

* `build_mot_plan`
* `build_cmot_plan`
* `build_pgc_array_plan`
* `build_tweezer_array_plan`

Better yet, the physics/control logic would first produce a **hardware-agnostic schedule or intermediate representation**, and then an OPX backend would compile that to QUA. That makes the logic testable without hardware and prevents OPX-specific details from infecting the experiment layer.

### 4) Device services

I would keep separate processes for hardware families because that is the correct place to isolate unstable vendor SDKs, blocking I/O, DLL crashes, and driver state.

Each device service should implement a narrow contract:

* `health()`
* `capabilities()`
* `configure(config)`
* `arm(run_context)`
* `start()`
* `stop()`
* `read_status()`
* `disarm()`

Camera services would additionally expose a frame publication contract. The important point is that the camera service returns **frame metadata and shared-memory references**, not giant NumPy arrays tunneled through multiple services.

Also, acquisition semantics should be explicit. Today there is ambiguous positional logic like “take frames `[-3]` and `[-1]`.” That should become a typed concept:

* `FrameRole.SIGNAL`
* `FrameRole.BACKGROUND`
* `FrameRole.FLAT`
* `FrameRole.REFERENCE`

A `ShotPlan` should declare which frame roles are expected per repetition, and the camera service should label them accordingly.

### 5) Analysis service

The current GUI server is doing too much: data retrieval, flat subtraction, fitting, NOA/density estimation, plotting, and returning results to scripts. That is a textbook boundary violation.

Analysis should be its own service or worker pool, built on top of a pure analysis library.

Responsibilities:

* Consume frame references and metadata
* Apply calibration and flat/background corrections
* Fit clouds
* Compute derived quantities like sigma, atom number, density
* Return a versioned `AnalysisResult`
* Publish fit failures and quality metrics

The UI can display these results, but it should not be the thing that computes them or owns the analysis pipeline.

### 6) Config and state store

`SharedParams.json` is currently trying to be too many things at once. I would split state into four categories:

1. **Hardware registry**
   IPs, ports, serial numbers, installation-specific paths, device names

2. **Calibrations**
   Camera calibrations, optical constants, conversion factors, analysis constants

3. **Session parameters**
   Operator-editable settings used for upcoming runs

4. **Per-run overrides**
   The actual parameters submitted for one run

These should be typed, validated, versioned, and stored centrally. SQLite is sufficient to start. Raw JSON files are fine for export/import or human review, but they should not be the live cross-process source of truth.

### 7) UI

The UI should become a client of the orchestrator, not a server in the middle of the acquisition path.

Its responsibilities:

* Show service health and capabilities
* Edit session parameters through typed forms
* Submit run requests
* Observe progress, plots, images, and alarms
* Allow manual device control where appropriate

Whether this is PySide6 or a browser UI is secondary. The important thing is that the UI can crash or disconnect without breaking an active run.

## Concurrency and state management

This is where the biggest reliability gains will come from.

### Use explicit state machines

I would model two state machines:

**Run state**

* `IDLE`
* `VALIDATING`
* `PREPARING`
* `ARMED`
* `RUNNING`
* `ACQUIRING`
* `ANALYZING`
* `SAVING`
* `COMPLETED`
* `FAILED`
* `CANCELLED`

**Device state**

* `DISCONNECTED`
* `CONNECTING`
* `READY`
* `CONFIGURED`
* `ARMED`
* `BUSY`
* `ERROR`

Right now, many failures are effectively “soft offline states” or GUI labels. In a control system, state needs to be explicit and queryable.

### Separate control traffic from image traffic

Control messages are tiny and latency-sensitive. Image data is large and throughput-sensitive. Those should not share the same transport.

I would use:

* **typed RPC** for commands, status, and metadata
* **shared memory or memory-mapped ring buffers** for frames
* optional **streaming events** for progress and monitoring

That directly fixes one of the biggest current inefficiencies: camera data being serialized camera server -> GUI server -> benchmark script on every shot.

### Immutable run snapshots

When a run starts, the orchestrator should freeze:

* experiment parameters
* hardware registry snapshot
* calibration versions
* compiled OPX config hash
* analysis version
* expected acquisition contract

The active run never consults live mutable session state again. That eliminates “what config did this run actually use?” ambiguity and makes saved results scientifically reproducible.

### Single-writer principle

No shared JSON file being edited by multiple actors. No direct script writes to runtime config. No GUI-side mutations that race with run execution.

Each piece of mutable state has one owner.

### Async orchestration, process isolation for drivers

I would run the orchestrator with `asyncio` or equivalent structured concurrency. Device services stay in separate processes. Inside a device process, threads are acceptable if a vendor SDK is blocking or callback-driven.

That gives you:

* timeouts and cancellation
* retries for transient failures
* bounded queues
* backpressure handling
* better crash isolation than a single threaded Tk-centric flow

### Closed-loop support as a first-class mode

Some experiments are just batch runs. Others are optimization loops that need “shot -> analyze -> update params -> next shot.”

That should be declared in the experiment definition, not hand-built in scripts. The orchestrator can then decide whether to block on analysis after each shot or run analysis asynchronously in batch mode.

## Testing strategy

This system is currently hard to test because hardware access, GUI code, and experiment logic are interwoven. From scratch, I would deliberately organize the code so that most of it is hardware-free and deterministic.

### Unit tests

For pure logic:

* parameter validation
* config generation
* duration normalization
* microsecond-to-QUA conversion and segmentation
* analysis math
* result reduction
* run summary generation

Property-based tests are especially useful for timing conversion and schedule generation because edge cases tend to hide there.

### Compiler and schedule tests

Do not test giant end-to-end scripts first. Test the intermediate plan.

Given parameters X and config Y, assert that the plan contains:

* the correct sequence phases
* the correct frame roles/counts
* the correct device requirements
* the correct trigger expectations

Then separately test the OPX backend that turns the plan into QUA.

### Contract tests for services

Every device service should pass the same contract tests against both:

* a fake implementation
* the real implementation when hardware is present

That is how you stop optional hardware, naming mismatches, and silent failure states from creeping in.

### Simulation and replay

You need fake devices:

* OPX simulator/stub
* Picam simulator using prerecorded frame sets
* Pixelfly simulator
* lock controller simulator

For analysis, use synthetic Gaussian clouds, noisy flats, bad fits, ROI edge cases, and missing-frame cases.

### Hardware-in-the-loop tests

For a system like this, HIL tests are unavoidable. But they should be a thin top layer, not the only layer.

I would run:

* per-device smoke tests
* one or two canonical end-to-end runs
* readiness/arming tests
* fail/recover tests

### CI and platform discipline

Because the runtime is Windows-centric, CI must include Windows. At minimum:

* linting and formatting
* static typing
* unit tests
* service contract tests with fakes
* packaging/bootstrap checks

Then run HIL tests on the lab machine or a dedicated validation machine.

## Maintainability and extensibility

A few design choices matter a lot here.

### One stable experiment API

No V1/V2 template coexistence. One interface. Old experiments either migrate or get wrapped behind adapters temporarily.

### One source of truth for runtime config

No direct file reads from arbitrary scripts. Scripts do not know where config files live.

### Typed models everywhere

The current “string numeric values in shared params” issue goes away if parameter schemas are first-class. The UI should render forms from schemas, not preserve ad hoc types accidentally.

### Plugin architecture for experiments and devices

New benchmark cases, camera types, or analysis methods should be additive. Register a new experiment plugin or device adapter; do not splice more branches into a monolith.

### Provenance and artifact discipline

For each run, store:

* run id
* parameter snapshot
* calibration versions
* device capability snapshot
* OPX program hash
* raw frame references
* analysis results
* logs/events
* git SHA and dirty diff, or a source snapshot artifact

That is much better than ad hoc JSON logs and scattered debug files.

### Structured observability

Use structured logs with correlation identifiers like `run_id`, `shot_id`, `frame_id`, `device`, `job_id`.

Expose metrics such as:

* service readiness
* compile time
* expected vs received frames
* dropped frames
* fit success rate
* device reconnect counts

A control system without good observability is very expensive to operate.

## Main weaknesses in the current implementation

The concrete bugs you listed are real, but the deeper weaknesses are systemic.

### 1) Accidental architecture

The repo is organized around runnable scripts and servers, but there is no true orchestrator. That is why lifecycle, readiness, persistence, and dependency handling are scattered.

### 2) Weak component boundaries

The GUI server is in the acquisition path and analysis path. Benchmark scripts manage devices directly. Older scripts bypass the service layer. That means there is no enforced platform boundary.

### 3) Unstructured IPC

Pickled localhost RPC is easy to start with and hard to grow. It has no schema, weak diagnostics, weak compatibility story, and it mixes control traffic with heavy payloads badly.

### 4) Shared mutable file state

A live `SharedParams.json`, direct file access by scripts, relative-path writes, and dynamic config generation all coexist. That is a recipe for configuration drift and irreproducible runs.

### 5) Implicit dependencies instead of declared capabilities

The Pixelfly requirement for a Picam run and the SLM mismatch are symptoms of the same design problem: required services are not a formal part of the experiment contract.

### 6) Business logic mixed with plumbing

The BenchmarkV2 bugs around empty statistics and duplicate save calls are not just coding mistakes. They happen because shot acquisition, analysis, aggregation, and persistence are all mixed inside one large execution path with no strong result model.

### 7) Error handling that hides root causes

Silent exception suppression turns programming errors into “offline” states. That is one of the most damaging failure modes in lab software because it destroys diagnosability.

### 8) Poor reproducibility and observability

Hard-coded IPs and paths, inconsistent logging, GUI-side state, hidden debug dumps, and mixed config sources all make it difficult to answer basic questions like “what exactly happened in that run?”

## Bottom line

If I were rebuilding this today, I would preserve the good physics/control ideas and replace the software shape around them.

The core move is this:

**turn experiments into typed plans, turn services into explicit capability providers, move frames through a proper data path, and make the orchestrator the sole owner of run lifecycle.**

That one shift addresses almost every weakness you identified: startup fragility, optional hardware confusion, config drift, duplicated image transport, silent failures, monolithic scripts, and weak testability.

The first contract I would define is:

**`RunRequest -> RunPlan -> ShotResult -> RunSummary`**

Once those objects exist and become the only things crossing major boundaries, the system becomes much easier to reason about, test, and extend.
