# ADR-0017: Lifecycle Disarm Returns to UNINIT
Status: Accepted

Managed device `Disarm` always tears down to `UNINIT`, including from `CONFIGURED`, `ARMED`, `RUNNING`, `STOPPED`, and `FAULT`; re-issuing `Disarm` at `UNINIT` is an idempotent no-op. `CONFIGURED` after disarm would preserve driver-cached configuration and violate the hidden-global-state mitigation in B13. Direct `Disarm` from `RUNNING` exists only for emergency abort / E-stop / watchdog paths; graceful cancel still uses shot-boundary `Stop` before `Disarm`. Reversal condition: revisit only if measured device throughput requires a warm reconfigure path, with explicit proof that no driver-cached last-set values can leak across runs.
