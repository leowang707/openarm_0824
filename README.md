# openarm_0824

Motor control GUI for:

- DaMiao DM-J6248P
- LANDA PA043

Current development branch:

```text
feature/lande-pa043
```

## Features

### DaMiao DM-J6248P

- Motor scan
- Enable / Disable
- MIT position control
- Position dial
- Speed / Kp / Kd settings
- Multi-motor control
- Motor ID configuration

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
gui_server.py
lande_motor.py
lande_backend.py
lande_probe.py
can_adapter.py
templates/custom_gui.html
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
