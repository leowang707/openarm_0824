# PA043 CAN Protocol Audit

This note records what is explicitly supported by the supplied
**蓝黛一体化伺服关节总成 使用手册** and what remains contradictory or
undocumented. The driver must not silently invent behavior for unresolved items.

## Verified transport

- Classic **CAN2.0A**
- standard 11-bit identifiers
- nominal bitrate **1 Mbps**
- documented frames are 8-byte Classic CAN frames
- PA043 CAN FD operation is **not documented**

## Verified control frames

Control traffic uses `CAN ID = Motor-ID`.

| Function | Data |
| --- | --- |
| Motor State | `FF FF FF FF FF FF FF FC` |
| Reset State | `FF FF FF FF FF FF FF FD` |
| Set current position to zero | `FF FF FF FF FF FF FF FE` |

Modes:

- `0x01` Servo
- `0x02` Torque-Position Mixed
- `0x03` Velocity
- `0x04` Torque

## Verified parameter frames

```text
CAN ID = Motor-ID + 0x600

READ:
67 index Data0 Data1 Data2 Data3 04 76

WRITE:
67 index Data0 Data1 Data2 Data3 15 76

REPLY:
Motor-ID index Data0 Data1 Data2 Data3 00 FF
```

`Data0..Data3` are little-endian. The manual documents Int32 and IEEE754
Float32 parameter types.

Repository-used indices:

| Index | Meaning |
| ---: | --- |
| 10 | Firmware Version |
| 11 | Control Mode |
| 36 | Motor ID |

Special commands:

| Index | Meaning | Repo status |
| ---: | --- | --- |
| `0x00` | Save parameters | implemented |
| `0x02` | Restore defaults | implemented; explicit confirmation required |
| `0x03` | Electric-angle calibration | implemented; explicit confirmation required |

Undefined bytes in these special commands are sent as zero.

## Manual contradictions / missing information

### 1. Motor-ID range vs parameter addressing

The manual says Motor ID is `0..1024`, but also specifies CAN2.0A standard
11-bit IDs and parameter ID `0x600 + Motor-ID`.

Therefore the stated parameter formula is representable only to:

```text
0x7FF - 0x600 = 0x1FF
```

The manual does not document parameter addressing for Motor IDs above `0x1FF`.
The driver refuses to guess it.

### 2. Parameter reply only carries one Motor-ID byte

The parameter reply payload allocates one byte to Motor-ID, while the manual
allows Motor IDs above 255. Upper Motor-ID bits are not documented.

The driver validates the reply CAN arbitration ID first and keeps the payload
Motor-ID as a low-byte consistency check.

### 3. Feedback Byte6 / Byte7 conflict

Page-12 table implies:

```text
Byte6 = Fault-ID
Byte7 = Temperature
```

Page-13 prose says:

```text
Byte6 = Temperature
Byte7 = Fault
```

The driver therefore exposes `raw_byte6` and `raw_byte7` and does not silently
assign `fault` or `temperature`.

### 4. Factory-default Motor ID is missing

The configurable range is given, but the factory-default Motor ID is not.

### 5. USB protocol is missing

The manual mentions a USB interface for maintenance but does not document:

- USB protocol
- framing
- baud semantics
- CDC vs vendor-specific transport
- relationship to CAN parameter access

A Windows COM port alone does not identify the application protocol.

### 6. Two physical CAN connector roles are missing

The supplied manual defines CAN_H/CAN_L but does not state whether two physical
connectors on a specific actuator revision are CAN IN/OUT, independent buses,
or simple pass-through.

### 7. Yellow LED meaning is missing

The supplied manual describes a blue status LED and buzzer behavior, but does
not define the yellow LED observed on the tested hardware.

### 8. CAN FD is not defined for PA043

The CAN adapter may support CAN FD, but the actuator manual specifies CAN2.0A
at 1 Mbps. The repo must remain on Classic CAN unless vendor documentation says
otherwise.

## Diagnostics

Parsed read-only probe:

```powershell
python lande_probe.py --adapter slcan --channel COM6
```

Passive raw listen:

```powershell
python lande_diag.py --adapter slcan --channel COM6 --action listen
```

Raw firmware scan:

```powershell
python lande_diag.py --adapter slcan --channel COM6 --action firmware-scan
```

Reset-State ID scan, no motion command:

```powershell
python lande_diag.py --adapter slcan --channel COM6 --action reset-scan
```
