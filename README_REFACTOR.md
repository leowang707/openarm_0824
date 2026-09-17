# Cross-platform CAN / Motor Registry Refactor

This refactor separates **CAN transport/adapters** from **motor protocols**.

## Architecture

```text
GUI / CLI
   |
MotorService
   |---------------------------|
Motor Registry                 Adapter Registry
   |                           |
PA043 / DaMiao            slcan / usbcan_a / gs_usb / socketcan
   |                           |
Motor protocol               python-can Bus
   |___________________________|
                CAN-H / CAN-L
```

## Keep unchanged from the current repo

- `lande_motor.py` (included here for convenience)
- existing root `usbcan_a.py` proprietary backend

## Replace / add

Copy the following into the repository root:

- `can_adapters/`
- `motors/`
- `motor_service.py`
- `can_adapter.py`
- `lande_backend.py`
- `lande_probe.py`
- `gui_server.py`
- `start_gui.py`
- `templates/custom_gui.html`
- `requirements.txt`

`patch_damiao.py` is no longer required by the new GUI path. It can remain in the repo unused until cleanup.

## Windows CANable2 / gs_usb

Install dependencies:

```powershell
pip install -r requirements.txt
```

The CANable2 USB interface must be accessible to PyUSB (for example through an appropriate WinUSB/libusbK binding).

Read-only PA043 test:

```powershell
python lande_probe.py --adapter gs_usb --channel 0 --scan-end 0x20
```

## Windows SLCAN

```powershell
python lande_probe.py --adapter slcan --channel COM5
```

## Windows USB-CAN-A

```powershell
python lande_probe.py --adapter usbcan_a --channel COM5
```

## Linux SocketCAN

Configure 1 Mbps first:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

Then:

```bash
python lande_probe.py --adapter socketcan --channel can0
```

## GUI

```powershell
python start_gui.py
```

Open `http://127.0.0.1:5000`.

PA043 motion is intentionally locked by default. After validating feedback and safe hold behavior on real hardware, enable it explicitly:

PowerShell:

```powershell
$env:ALLOW_PA043_MOTION="1"
python start_gui.py
```

Linux:

```bash
ALLOW_PA043_MOTION=1 python start_gui.py
```
