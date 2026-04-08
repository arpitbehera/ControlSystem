# Neutral Atom Lab Control System Platform Design

**Date:** 2026-04-08
**Status:** Approved in conversation, pending final written review

## Purpose

Define the software architecture for a long-lived replacement of the current lab control system for a neutral atom optical tweezer experiment. The platform should remain extensible for at least the next 15 years, support incremental device additions, and avoid repeating the current system's coupling between orchestration, hardware control, analysis, and UI.

## Why This Exists

The current system has the right instincts but weakly enforced boundaries. Control flow, device access, analysis, GUI behavior, and persistence leak across one another. The new system should formalize those boundaries so that:

- `PC1` remains the control anchor for the lab
- new devices can be added as stable software abstractions
- high-volume data does not move wastefully through the system
- runs are reproducible and testable
- failures are observable and recoverable at safe boundaries

## System Shape

The platform should be a distributed control system with a centralized orchestrator.

- `PC1` is the fixed home of the orchestrator in v1
- `PC2` hosts the SLM stack
- `PC3` hosts miscellaneous USB and network attached devices as explicit per-device services
- `PC4` is optional and should remain a visualization/dashboard client rather than part of the control path

All lab PCs communicate over Ethernet. The orchestrator owns run lifecycle. Other machines expose device services to it over the network.

## Architectural Direction

The codebase should follow a modular-monolith design with a small number of supervised runtime processes.

The orchestrator is the sole owner of:

- run validation
- run planning
- device coordination
- state transitions
- failure policy
- result aggregation

The UI/dashboard is a client of the orchestrator and is not allowed to own hardware state or sit in the acquisition path.

## Communication Planes

The system should explicitly separate communication into two planes.

### Control Plane

Used for small typed messages such as:

- service discovery and registration
- health and heartbeat traffic
- capabilities exchange
- configuration and arming commands
- run control commands
- status and event streaming
- `ShotResult` and `RunSummary` delivery

The control plane should be the backbone of orchestration. The specific RPC technology is less important than the stability of the contracts carried over it.

### Data Plane

Used for high-volume payloads such as:

- raw camera images
- SLM phase patterns
- other bulk binary artifacts

The default rule is that large payloads remain local to the host that owns them unless there is a concrete reason to move them.

For this lab:

- EMCCD data arrives on `PC1` through CameraLink
- GPU-direct processing is used for fast local processing and feedback
- feedback commands are sent to the `OPX+` via input/output streams
- the orchestrator should receive metadata and derived outputs, not the raw images
- dashboards may subscribe to visualization-oriented streams separately from the orchestrator

This keeps the control path lean and avoids wasting bandwidth and latency budget on unnecessary data motion.

## Device Abstractions

The platform should support two kinds of first-class software abstractions.

### Managed Devices

Managed devices are hardware families with their own computer-facing process or service. Examples:

- cameras
- SLMs
- power supplies
- laser locking electronics
- motorized stages
- piezo controllers
- Arduinos
- Raspberry Pis

These expose network-visible services to the orchestrator.

### Modeled Devices

Modeled devices are lab elements that do not own their own service but still deserve first-class software representation because they have independent semantics and calibration. Examples:

- AOMs
- AODs
- analog shutters
- coils
- other OPX-driven analog elements

A modeled device should carry:

- identity and ownership
- calibration data
- allowed operating ranges
- translation rules from physical intent to hardware signals
- dependency on the underlying controller, typically `OPX+`

Example: an `AOM` abstraction should know how requested optical power maps to control voltage or waveform amplitude, including calibration and nonlinear corrections where needed.

Modeled devices must appear in the run model even if they are not separate network services.

## Shared Lifecycle Contract

Every managed device service should expose the same core lifecycle contract:

- `health`
- `capabilities`
- `configure`
- `arm`
- `start`
- `stop`
- `status`
- `disarm`

This common contract allows the orchestrator to coordinate diverse devices uniformly while keeping device-specific detail out of the run coordination layer.

Variation belongs in:

- capability models
- typed device-specific configuration
- device-specific extension APIs where required

Examples:

- a camera advertises trigger modes, frame products, and expected frame roles
- an SLM advertises upload limits, apply latency, and supported pattern modes
- a power supply advertises channels, ramp behavior, and protection features

## Run Model

The run model should be explicit and typed:

- `RunRequest`: operator intent and requested experiment parameters
- `RunPlan`: frozen executable plan derived from request, configuration, and calibration
- `ShotResult`: per-shot outcome including metadata, control-relevant analysis outputs, and status
- `RunSummary`: aggregate run outcome, provenance, and completion status

The orchestrator should:

1. validate the `RunRequest`
2. freeze a `RunPlan`
3. coordinate devices through the shared lifecycle contract
4. consume `ShotResult` objects
5. emit a `RunSummary`

## Testing Strategy

Testing is a first-class part of the initial architecture, not a later cleanup step.

The first milestone should include:

- contract tests for the shared lifecycle contract
- fake-device implementations used in automated tests
- orchestrator integration tests for discovery, configure, arm, start, stop, and state transitions
- deterministic tests for `RunRequest -> RunPlan -> ShotResult -> RunSummary`
- failure-path tests for missing service, unhealthy service, timeout, invalid capability match, and interrupted run
- a local end-to-end demo script that boots the fake environment and runs one successful fake shot

Design rule:

**No real-device integration without a fake and a contract test first.**

This makes the platform extensible without depending on ad hoc lab-only manual testing as the main proof of correctness.

## Failure Handling and Recovery

The system should support supervised recovery with explicit resume policy.

Each device service should have:

- heartbeat expectations
- timeout policy
- bounded restart or reconnect behavior

The orchestrator should decide, based on device role and run phase, whether to:

- continue
- retry
- skip a noncritical device
- mark the shot failed
- abort the run safely

Resume should be checkpoint-based, not magical. For v1:

- resumability is defined at shot boundaries
- mid-shot failure is treated as a failed shot
- failed shots may be retried only if the run policy allows it

Examples:

- dashboard failure should not affect an active run
- noncritical service loss may allow continuation after recovery
- required device failure before a shot may allow recovery and retry
- `OPX+` or required camera failure mid-shot should fail the shot and recover only at the next safe boundary

## First Milestone

The first milestone should prove one vertical slice of the new platform rather than trying to model the entire lab.

### Included

- orchestrator process on `PC1`
- service discovery and registration across lab PCs
- shared lifecycle contract for device services
- one fake device host exposing at least one fake service
- one fake `OPX/camera` execution path
- typed run objects: `RunRequest`, `RunPlan`, `ShotResult`, `RunSummary`
- explicit run state machine
- control-plane versus data-plane split enforced in design
- a minimal dashboard/client that can observe run state and results
- automated tests for the contract and the fake execution slice

### Excluded

- all real hardware integrations
- office-remote job submission
- full calibration management for every device
- rich GUI workflows
- complete persistence and provenance system
- final data-plane implementation for every payload type

### First Milestone Success Condition

A successful first milestone means:

- the orchestrator boots on `PC1`
- fake or real device services can be discovered across PCs
- a `RunRequest` can be submitted
- the run state machine advances visibly
- a `ShotResult` is received from a fake `camera/OPX` pipeline

## Runtime Flow for the First Milestone

1. A client submits a `RunRequest` to the orchestrator on `PC1`.
2. The orchestrator validates it and freezes a minimal `RunPlan`.
3. The orchestrator discovers required services and queries `health` and `capabilities`.
4. The orchestrator issues `configure` and `arm` to participating services.
5. The fake execution path starts and advances the run state machine.
6. The fake `camera/OPX` path produces a `ShotResult`.
7. The orchestrator consumes the `ShotResult`, updates run state, and emits a `RunSummary`.
8. A dashboard/client observes state transitions and results without entering the execution path.

## Recommended Early Phases

### Phase 1: Control-Plane Skeleton

Define and prove:

- typed contracts
- orchestrator on `PC1`
- service discovery and registration
- shared lifecycle contract
- run state machine
- heartbeat and timeout model
- recovery policy at shot boundaries

### Phase 2: Fake-Device Execution Slice

Prove the architecture end to end with no real hardware dependency:

- fake device host
- fake `OPX` service
- fake camera/analysis path
- `RunRequest -> RunPlan -> ShotResult -> RunSummary`
- contract tests
- orchestrator integration tests
- successful and failure/retry demo runs

### Phase 3: Modeled Device and Calibration Foundation

Add support for OPX-driven analog lab elements:

- modeled-device abstractions
- calibration translation interfaces
- safe-range validation
- inclusion of modeled devices in `RunPlan`

### Phase 4: First Real Hardware Adapters

Only after the contracts are stable:

- one real device integration on `PC1`
- one real remote device integration on `PC2` or `PC3`
- smoke tests and supervised recovery behavior

## Open Decisions Deferred Beyond This Spec

These are intentionally left for later detailed planning:

- exact RPC technology
- exact bulk-data transport implementation
- persistence schema and storage engine details
- remote office job-submission architecture
- full GUI/dashboard design
- complete device family taxonomy and calibration schema

## Guiding Principle

The platform should turn experiments into typed plans, services into explicit capability providers, large payloads into data-plane artifacts, and the orchestrator into the sole owner of run lifecycle.

That is the shift that makes the system easier to reason about, test, extend, and operate over the long term.
