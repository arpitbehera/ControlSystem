# 02 — Hardware Topology

## Layer-to-machine assignment

| Machine | Role | Hosted processes | Why |
|---|---|---|---|
| **HP Z2 Tower (`PC1`)** | Latency domain: broker + framegrabber + GPU pipeline + raw spool | Broker process; Andor service; Compute service; Data-lake writer | (a) BitFlow Axion 1xB + RTX 4000 Ada must share PCIe topology for GPUDirect for Video. (b) Andor iXon is PCIe-bound. (c) Co-located avoids any cross-host hop on the rearrangement loop. (d) A8 risk bounded by process isolation + by keeping calibration registry off this host. |
| **HP EliteDesk 800 G6** | Control + persistence domain: scheduler, compiler, calibration DAG, metadata DB | Scheduler + compiler; Postgres; read-only dashboard backend; TFTP for network backups | (a) Calibration registry on a different host than broker → Tower crash never poisons history. (b) Scheduler is the back-pressure surface when broker is unreachable. (c) Win 10 LTSC: longest support runway, lowest churn. |
| **HP Z2 Mini (`PC2`)** | SLM domain + secondary compute | SLM device service; holography compute; emulator host | (a) SLM HDMI cannot relocate. (b) Mini's GPU + 64 GB RAM is sufficient for Gerchberg–Saxton / WPGS. (c) Provides a fallback GPU service so Tower is not a single point of failure for general GPU work. |
| **Lenovo ThinkCentre (`PC3`)** | Slow-instrument domain | GigE camera services; USB camera services; misc instrument services (Arduinos, PSUs, oscilloscopes) | (a) GigE / USB don't need GPU. (b) Isolates slow-image traffic from the Tower NIC. (c) 16 GB sufficient for buffered acquisition. |
| **OPX+ + QM router** | Real-time domain | PPU firmware + QUA bytecode | Vendor-required topology; AOD waveform synthesis end-to-end. |

## Network topology

```
                       Institute network (upstream)
                                    │ ether1 (WAN)
                       ┌────────────▼────────────┐
                       │ MikroTik RB3011UiAS-RM  │ router + firewall + NTP + DHCP
                       │ ether2 (mgmt, chip 1)   │
                       │ ether3 (trunk to Cisco) │
                       └────────────┬────────────┘
                                    │ trunk: VLAN 10/20/30/40 (VLAN 50 EXCLUDED)
                                    ▼
            ┌─────────────────────────────────────────────────────────┐
            │             Cisco Catalyst 3560G-48TS-S                  │
            │              32 Gbps non-blocking fabric                 │
            └─┬───────┬──────┬───────┬───────┬───────┬───────┬───────┘
             Gi0/1   /2-5   /6-9    /10-15  /16-47   /48     SFP×4
             trunk  VLAN 50 VLAN 10 VLAN 20  shut    mgmt    shut
                    OPX+   hosts    cameras  reserve console
                    QM-r
                    Tower-broker-NIC
```

### VLAN plan

| VLAN | Name | Subnet | Members | Properties |
|---|---|---|---|---|
| 10 | `lab-core` | 10.10.10.0/24 | Tower control NIC, EliteDesk, Z2 Mini, ThinkCentre, lab terminals | Control plane traffic |
| 20 | `instruments` | 10.10.20.0/24 | ProEM HS1024, all DMK GigE cameras | GigE data plane; jumbo opt-in only after measurement |
| 30 | `mgmt` | 10.10.30.0/24 | Switch mgmt IP, RB3011 ether2, NTP server | OOB admin only |
| 40 | `guest` | 10.10.40.0/24 | Off-lab analyst laptops | Read-only access to dashboard + replica |
| **50** | **`opx-rt`** | **192.168.88.0/24** (QM-router DHCP) | OPX+ controller(s), QM router, Tower broker NIC | **L2-only on the 3560G. No SVI on RB3011. Trust enclave.** |

### Critical-path rule

The rearrangement loop never traverses the RB3011. VLAN 50 lives on Cisco fabric only. The Tower is dual-homed: broker NIC on VLAN 50 (192.168.88.x), control NIC on VLAN 10 (10.10.10.10). The broker binds `QuantumMachinesManager` to the VLAN-50 interface address explicitly. Anti-routing/anti-bridging policy on the Tower (no ICS, no bridge between adapters) is required to prevent leaking VLAN 50 onto VLAN 10.

### Per-host reachability

| From → to | OPX+ (VLAN 50) | Postgres (VLAN 10) | Cameras (VLAN 20) |
|---|---|---|---|
| Tower broker | ✓ (direct L2) | ✓ (control NIC) | ✓ (via L3 on RB3011) |
| EliteDesk | ✗ (no L3 to VLAN 50; status proxied via Tower broker) | ✓ (local) | ✓ (via L3) |
| Mini | ✗ (status proxied) | ✓ | ✓ |
| ThinkCentre | ✗ (status proxied) | ✓ | ✓ (direct L2 if on VLAN 20) |
| Guest (off-lab) | ✗ | read-only replica only | ✗ |

This resolves critique F-10: OPX management/status reachability is via the Tower broker's narrow authenticated status API on VLAN 10. Other hosts never directly route into VLAN 50.

## Per-host process discipline

### Tower (the latency-pinned host)

- **Broker** = single Python process, RT priority (after Phase 0A confirmation per critique F-09; default to `HIGH_PRIORITY_CLASS` until benchmarks justify `REALTIME_PRIORITY_CLASS`). Pinned to a fixed subset of P-cores (e.g. cores 0–7). No GUI. No other Python.
- **Compute service** = separate process, same GPU; gated by a Postgres-backed mutex held by the scheduler whenever a run is `armed` or `executing`.
- **Andor service** = separate Windows service. SDK ownership lives here. **The broker, not this service, owns BitFlow capture and GPU buffer registration during a run.** Per critique F-09, the exact buffer-handoff path between Andor SDK and the in-process BitFlow client is a Phase 0A deliverable.
- **Data lake writer** = separate process. Consumes shot records over shared-memory queue. Writes raw to durable local spool first; replicates off-host on its own schedule.

### EliteDesk

- **Scheduler / compiler / DAG runner** = single Python process per service; long-running. Hot reload via systemd-style service controllers (Windows service wrappers, e.g. `nssm`).
- **Postgres** on local NVMe. WAL streaming to an off-host backup target (NAS, USB rotation, or institutional storage). Not to the Tower (same failure domain as the broker).
- **Read-only dashboard backend** = FastAPI on a separate port, separate process. Cannot mutate any DB row (DB role enforces).

### Mini

- **SLM service** + **holography compute** in one process. SLM is HDMI-stateful; one owner only.
- **Emulator** = separate process; serves Layer-4 emulator compilation target.

### ThinkCentre

- **One Windows service per camera-family**. Each implements the lifecycle contract.
- **Misc instrument services** for Arduinos / PSUs / scopes / spectrum analyzers; one service per family.

## Time sync

- RB3011 acts as stratum-2 NTP server, peering upstream to institute NTP (preferred) or public pool (fallback). All hosts sync to it.
- Drift goal: ≤ 10 ms across all hosts.
- OPX+ timestamps establish **experimental** timing. NTP timestamps are **observational metadata** only (per critique F-18).
- Per-host weekly check: `w32tm /query /status` (Windows). Sustained offset > 10 ms is an alarmable condition.
- PTP is not achievable on installed gear; documented in §06.

## Failure semantics summary

| Failed host | Effect on in-flight run | Effect on history | Recovery |
|---|---|---|---|
| Tower | In-flight shot fails (broker is the loop owner); local raw spool may have partial bytes; safety plane brings RF/AOD to safe state | History intact (registry is on EliteDesk) | Power cycle Tower (~5 min); broker reconnects to OPX; scheduler marks failed shot |
| EliteDesk | OPX run continues if broker is alive; broker buffers shot records to local spool; new submissions blocked; DAG halts | Postgres WAL on NVMe + off-host replica = no committed-row loss | Restart EliteDesk; broker drains spool into Postgres |
| Mini | SLM frame freezes at last value (HDMI is stateful); rearrangement unaffected | History intact | Restart; recompute hologram from current descriptor |
| ThinkCentre | Slow-camera shots fail; Andor on Tower unaffected | History intact | Restart |
| OPX+ | Run halts; safety plane fires | History intact | Restart cluster via QM admin; reconnect |
| Lab switch | Everything stops | History intact (Postgres durable) | Switch reboot; hosts reconnect |

The "history intact" guarantee depends on the durable-commit protocol in §05 (no row commits without raw-data manifest + checksum committed first).
