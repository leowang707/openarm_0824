# openarm_0824

Motor control GUI for:

- DaMiao DM-J6248P
- DaMiao DM-J8009P-2EC
- LANDA PA043

Current development branch:

```text
feature/lande-pa043
```

## Features

### DaMiao DM-J6248P

- Classic CAN, default 1 Mbps
- Motor scan (automatic discovery IDs 1..15 with current dependency)
- Enable / Disable
- MIT / POS_VEL / VEL / FORCE_POS
- Position dial for MIT / POS_VEL
- Multi-motor control

### DaMiao DM-J8009P-2EC

- Classic CAN profile: Standard CAN, 1 Mbps per supplied V1.0 manual
- Motor scan (automatic discovery IDs 1..15 with current dependency)
- Enable / Disable
- MIT / POS_VEL / VEL
- Position dial for MIT / POS_VEL
- Uses the DaMiao SDK `8009` mapping preset
- One tested **J8009-series** unit (exact P/non-P variant unconfirmed) reported
  FW `6417 / 004`, CAN ID `0x001`, MASTER ID `0x011`, and `CAN Baud: 5.00Mbps`.
- The `canfd_1m_5m` entry is an **unverified candidate**, not an implemented path
  or proof of that unit's nominal/data timing. See `knowledge/HARDWARE_OBSERVATIONS.md`.

### LANDA PA043

- CAN 2.0A, 1 Mbps
- Motor ID scan
- Firmware read
- Control mode read
- Parameter read / write
- Servo mode
- Torque-Position mode
- Velocity mode
- Torque mode
- GUI motor-model selection

PA043 motion control is still under hardware validation.

## Bus profiles and adapter capabilities

Motor brand/model, bus profile, host backend and actual device/channel are separate concepts.

```text
LANDA PA043
  classic_1m          implemented

DaMiao DM-J6248P
  classic_1m          implemented

DaMiao DM-J8009P-2EC
  classic_1m          implemented
  canfd_1m_5m         unverified candidate, not implemented
```

Current adapter backends (`slcan`, `usbcan_a`, `gs_usb`, and `socketcan`) are
explicitly declared Classic-CAN-only until a CAN-FD backend is implemented and
validated. The service rejects unimplemented/incompatible profiles before the
motor-control path is opened.

## Setup

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## How to Use

### 1. Connect Hardware

Connect the USB-CAN adapter to the PC.

For PA043:

```text
CAN-H -> CAN-H
CAN-L -> CAN-L
Power -> 24V
```

CAN bitrate:

```text
1 Mbps
```

### 2. Check COM Port

```powershell
python -m serial.tools.list_ports -v
```

Example:

```text
COM5
```

### 3. Run GUI

```powershell
python start_gui.py
```

Open:

```text
http://127.0.0.1:5000
```

### 4. Select Motor Type

In the GUI choose:

```text
DaMiao DM-J6248P
```

or:

```text
DaMiao DM-J8009P-2EC
```

or:

```text
LANDA PA043
```

Then select the CAN adapter and COM port.

### 5. Connect and Scan

Press:

```text
Connect / Scan
```

The GUI will scan available motor IDs.

For PA043 it will read:

```text
Motor ID
Firmware Version
Control Mode
```

### 6. PA043 Read-only Test

Before motion testing, use:

```powershell
python lande_probe.py --port COM5
```

This only reads motor parameters and does not enable motor motion.

### 7. DaMiao Control

```text
Connect
-> Scan
-> Select Motor
-> Enable
-> Set Target Position
-> Disable
```

### 8. PA043 Control

PA043 supports:

```text
Servo
Torque-Position
Velocity
Torque
```

Current GUI motion control is still under hardware validation.

## Main Files

```text
gui_server.py                     existing HTTP API and control loop
templates/custom_gui.html         brand/model/profile/backend selection + dial
motor_service.py                 one session / one selected model / one bus
can_profiles.py                  neutral BusProfile metadata
motors/damiao/                   shared Classic backend + model presets
motors/lande/                    PA043 backend + protocol
can_adapters/                    separate host backends; not motor vendors
lande_motor.py                   compatibility import shim
lande_probe.py / lande_diag.py    existing command-line entry points
tools/verify_refactor.py          offline test runner
```

## Current Status

```text
DaMiao GUI            ✓
PA043 driver          ✓
PA043 parameter read  ✓
PA043 GUI backend     ✓
PA043 GUI scan        Testing
PA043 motion          Pending hardware validation
```

## Git

Fork:

```text
https://github.com/leowang707/openarm_0824
```

Branch:

```text
feature/lande-pa043
```

## PA043 protocol audit and diagnostics

PA043 uses **Classic CAN 2.0A standard frames at 1 Mbps**. The supplied vendor
manual does not define CAN FD for this actuator.

- `knowledge/PA043_CAN_PROTOCOL_AUDIT.md` records verified mappings,
  contradictions, and undocumented behavior.
- `lande_probe.py` performs parsed, read-only parameter discovery.
- `lande_diag.py` performs raw parser-independent diagnostics.

## DaMiao protocol audit

- `knowledge/DAMIAO_PROTOCOL_AUDIT.md` compares DM-J6248P and DM-J8009P-2EC against the supplied J8009P manual, DaMiao official SDK, and the `damiao-motor` dependency.
- DM-J6248P exposes MIT / POS_VEL / VEL / FORCE_POS.
- DM-J8009P-2EC exposes the three modes explicitly documented in its V1.0 manual: MIT / POS_VEL / VEL.


## Vendor refactor package

See `knowledge/ARCHITECTURE.md` for the complete design and
`knowledge/REFACTOR_RUNBOOK.md` for the local migration and validation sequence.
`knowledge/HARDWARE_OBSERVATIONS.md` separates user-observed facts from candidates.

Runtime UART is intentionally excluded. No CAN-FD backend or Hybrid control
has been enabled. Existing motor keys and HTTP routes are retained.

The GUI now groups models by vendor. `gs_usb` is a direct USB host backend;
`socketcan` is a Linux OS interface backend. They are not merged, and the
application never automatically unbinds a kernel driver or switches protocols.

CH340 serial devices remain listed but are not automatically classified as
Waveshare. Select `usbcan_a` and the actual channel explicitly after identifying
hardware. Selecting an interface is not the same as receiving a motor reply.

No-hardware catalog (does not enumerate devices unless `--devices` is added):

```powershell
python -m diagnostics.catalog
```

Validation with the active project's interpreter:

```powershell
.\.venv\Scripts\python.exe tools/verify_refactor.py
```

`--mock-only` runs syntax and isolated architecture tests only. It does not
approve the dependency integration, USB drivers, CAN hardware, or motion.
