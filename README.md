# openarm_0824

Cross-platform motor-control GUI and CAN abstraction for:

- DaMiao DM-J6248P
- DaMiao DM-J8009P-2EC
- LANDA PA043

Current development branch:

```text
refactor/vendor-layout-20260921
```

## Features

### DaMiao DM-J6248P

- Classic CAN, default 1 Mbps
- Automatic motor discovery for logical IDs 1..15 with the current dependency
- Enable / Disable
- MIT / POS_VEL / VEL / FORCE_POS
- Position dial for MIT / POS_VEL
- Multi-motor control
- GUI-adjustable motion speed, MIT Kp and Kd

### DaMiao DM-J8009P-2EC

- Classic CAN profile: Standard CAN, 1 Mbps per supplied V1.0 manual
- Automatic motor discovery for logical IDs 1..15 with the current dependency
- Enable / Disable
- MIT / POS_VEL / VEL
- Position dial for MIT / POS_VEL
- Uses the DaMiao SDK `8009` mapping preset
- One tested J8009-series unit, with exact P/non-P variant still unconfirmed,
  reported FW `6417 / 004`, CAN ID `0x001`, MASTER ID `0x011`, and
  `CAN Baud: 5.00Mbps`
- `canfd_1m_5m` remains an unverified candidate and is not an implemented
  runtime path

See `knowledge/HARDWARE_OBSERVATIONS.md` for hardware observations and
unverified candidates.

### LANDA PA043

- Classic CAN 2.0A, 1 Mbps
- Motor ID discovery
- Firmware read
- Control-mode read
- Parameter read / write
- Servo mode
- Torque-Position mode
- Velocity mode
- Torque mode
- GUI motor-model selection

PA043 motion control remains hardware-validation gated.

## Architecture

Motor identity, motor protocol, CAN bus profile, host backend, and physical
device/channel are separate concepts.

```text
Motor Brand
    |
Motor Model
    |
Motor Protocol
    |
Bus Profile
    |
CAN Backend / Host Interface
    |
Device / Channel
    |
Physical CAN Bus
```

Example:

```text
DaMiao DM-J6248P
  protocol: damiao_classic
  profile:  classic_1m
  backend:  usbcan_a / slcan / gs_usb / socketcan
  channel:  COMx / device index / can0
```

## Bus Profiles

```text
LANDA PA043
  classic_1m          implemented

DaMiao DM-J6248P
  classic_1m          implemented

DaMiao DM-J8009P-2EC
  classic_1m          implemented
  canfd_1m_5m         unverified candidate, not implemented
```

A bus profile defines transport requirements such as Classic CAN vs CAN-FD and
nominal/data bitrate. It does not identify the USB adapter.

`1 Mbps` is CAN bus bitrate. It is not the host command-loop frequency.

## CAN Backends

Current host backends:

```text
slcan       SLCAN / Lawicel serial protocol
usbcan_a    Waveshare USB-CAN-A serial protocol
gs_usb      gs_usb / CANable / candleLight direct USB
socketcan   Linux SocketCAN interface
```

All currently exposed runtime backends are treated as Classic-CAN-only until
a CAN-FD backend is implemented and hardware validated.

### Explicit backend selection

The GUI intentionally does not expose automatic backend selection.

Initial state:

```text
CAN Backend / Host Interface
  請選擇 CAN Backend

Device / Channel
  請先選擇 CAN Backend
```

The operator must explicitly choose the backend first. Only then is the
Device / Channel list populated with devices that match the selected backend.

This avoids treating a serial COM port as proof of a particular CAN protocol.

CH340 devices are especially ambiguous: the same USB-serial family can be used
by a USB-CAN adapter or by an ordinary UART device. Therefore a CH340 port is
not automatically classified as Waveshare USB-CAN-A.

For a verified Waveshare USB-CAN-A setup, explicitly select:

```text
CAN Backend: Waveshare USB-CAN-A
Channel:     COMx
```

The lower-level adapter registry still retains internal auto-resolution logic
for internal APIs, tests, and future discovery work, but the GUI does not
use it as an operator-facing default.

## Setup

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the GUI

```powershell
python start_gui.py
```

Open:

```text
http://127.0.0.1:5000
```

## GUI Connection Workflow

1. Select **Motor Brand**.
2. Select **Motor Model**.
3. Select **Bus Profile**.
4. Select **CAN Backend / Host Interface**.
5. Select **Device / Channel**.
6. Press **連線並掃描馬達**.

The GUI does not guess the CAN backend.

### Connection buttons

**重新偵測 CAN 裝置**

Re-enumerates host-side CAN/USB/serial devices and refreshes the Device /
Channel list.

It does not open the CAN bus, scan motor IDs, enable a motor, or send motion
commands.

**連線並掃描馬達**

Validates the selected motor/profile/backend, opens the CAN adapter, creates
the motor backend, and scans the configured motor-ID range.

**重新掃描馬達**

Reuses the currently open CAN bus and scans for motors again. It does not reopen
the host adapter.

**斷線**

Stops the motor backend, shuts down the CAN bus, releases the host device, and
clears the active motor list.

## Connection-State Display

The connect button distinguishes host-CAN connection from actual motor
discovery.

```text
連線並掃描馬達
  no CAN connection

CAN 已連線
  host adapter/bus is open, but no motor has been discovered

已連線
  host adapter/bus is open and at least one motor has been discovered
```

The connected-state button is disabled to prevent accidentally reopening the
same CAN session.

Opening an adapter is not itself proof that a motor is online.

## DaMiao Control

Typical workflow:

```text
Select Brand / Model
-> Select Bus Profile
-> Select CAN Backend
-> Select Device / Channel
-> Connect and Scan
-> Select Motor
-> Select Control Mode
-> Enable
-> Set Target
-> Disable
```

### MIT mode

MIT mode sends:

```text
target position
target velocity
Kp / stiffness
Kd / damping
feed-forward torque
```

The GUI exposes motion speed, Kp, and Kd for tuning.

Position error under load can depend on stiffness, damping, friction, gravity,
and external load. Increase gains conservatively and stop testing if the motor
begins to oscillate or behave unexpectedly.

### POS_VEL mode

POS_VEL sends:

```text
target position
velocity limit
```

The velocity field is a motion limit, not MIT-style target velocity.

## PA043 Read-Only Test

Before PA043 motion testing:

```powershell
python lande_probe.py --port COM5
```

This reads motor parameters without enabling motor motion.

PA043 GUI motion remains locked by default until real feedback and safe hold
behavior are validated.

## Main Files

```text
gui_server.py                     HTTP API + GUI control loop
templates/custom_gui.html         browser UI
motor_service.py                  active motor/backend/CAN session
can_profiles.py                   neutral bus-profile metadata

motors/damiao/
  classic.py                      shared DaMiao Classic-CAN backend
  models.py                       model identity and SDK mappings
  profiles.py                     bus profiles
  common.py                       mode mappings and scan bounds

motors/lande/
  pa043.py                        PA043 application backend
  protocol.py                     PA043 wire protocol

can_adapters/
  registry.py                     adapter discovery/open abstraction
  slcan.py                        SLCAN backend
  usbcan_a.py                     Waveshare USB-CAN-A backend
  gs_usb.py                       gs_usb backend
  socketcan.py                    SocketCAN backend

lande_motor.py                    legacy compatibility import shim
lande_probe.py / lande_diag.py    PA043 diagnostics
tools/verify_refactor.py          offline validation runner
```

## Validation

Run with the active project interpreter:

```powershell
python tools\verify_refactor.py
git --no-pager diff --check
```

The verifier covers:

- Python syntax
- isolated architecture/contract tests
- dependency integration checks
- profile and adapter safety contracts
- legacy import compatibility

Passing offline validation does not prove:

- USB driver correctness on every host
- physical CAN wiring
- motor identity
- CAN-FD operation
- safe motion under load

Physical motor testing remains a separate validation step.

## Current Status

```text
Vendor/package refactor           implemented
DaMiao J6248P Classic-CAN GUI     bench tested
DaMiao J6248P MIT motion          bench tuning in progress
DaMiao J8009P Classic-CAN path    implemented; hardware validation incomplete
DaMiao CAN-FD candidate           not implemented
PA043 protocol/backend            implemented
PA043 parameter access            implemented
PA043 motion                      pending hardware validation
Explicit GUI backend selection    implemented
GUI Auto backend selection        intentionally disabled
```

## Diagnostics

No-hardware catalog:

```powershell
python -m diagnostics.catalog
```

## Documentation

- `knowledge/ARCHITECTURE.md` - runtime architecture and ownership boundaries
- `knowledge/REFACTOR_RUNBOOK.md` - migration and validation workflow
- `knowledge/HARDWARE_OBSERVATIONS.md` - observed hardware facts vs candidates
- `knowledge/DAMIAO_PROTOCOL_AUDIT.md` - DaMiao protocol/model audit

## Git

Fork:

```text
https://github.com/leowang707/openarm_0824
```

Current branch:

```text
refactor/vendor-layout-20260921
```

## Safety Notes

- Motor enable and motion commands can move hardware immediately.
- Confirm CAN wiring, supply voltage, motor model, IDs, control mode, and limits
  before enabling motion.
- Do not infer CAN protocol from a COM port alone.
- CAN-FD candidates are not enabled until both protocol and host-backend support
  are validated.
- PA043 destructive parameter operations remain guarded.
