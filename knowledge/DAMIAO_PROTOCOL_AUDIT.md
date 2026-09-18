# DaMiao DM-J6248P / DM-J8009P-2EC protocol audit

## Sources

- DM-J8009P-2EC V1.0 manual supplied for this project:
  https://doc.switch-science.com/media/files/0eacb9ba-85e6-4761-93df-92773000fddb.pdf
- DaMiao official SDK: https://github.com/dmBots/motor-sdk
- Python dependency used by this repo: `damiao-motor>=1.0.6`
  (source: https://github.com/jia-xie/python-damiao-driver)

## Transport / feedback

The supplied J8009P V1.0 manual documents standard CAN at 1 Mbps. The common
feedback frame uses `MST_ID` as arbitration ID and packs logical motor ID/error,
position (16 bit), velocity (12 bit), torque (12 bit), MOS temperature and rotor
temperature into 8 bytes.

## MIT protocol

MIT uses the command motor/ESC ID and packs:

- Position: 16 bit
- Velocity: 12 bit
- Kp: 12 bit, range 0..500
- Kd: 12 bit, range 0..5
- Torque: 12 bit

Official SDK default mappings:

```text
DM8009  : P_MAX=12.5,   V_MAX=45, T_MAX=54
DM6248P : P_MAX=12.566, V_MAX=20, T_MAX=120
```

The `damiao-motor>=1.0.6` package contains the same `8009` and `6248P` presets.

## POS_VEL

```text
CAN ID = 0x100 + Motor ID
D0-D3  = target position, Float32 little-endian
D4-D7  = velocity limit, Float32 little-endian
```

## VEL

```text
CAN ID = 0x200 + Motor ID
D0-D3  = target velocity, Float32 little-endian
```

The Python dependency pads the Classic CAN frame to 8 bytes.

## FORCE_POS

Generic DaMiao protocol / DM-J6248P support:

```text
CAN ID = 0x300 + Motor ID
D0-D3  = target position, Float32 little-endian
D4-D5  = velocity limit x100
D6-D7  = current/torque-limit ratio x10000
```

The supplied **DM-J8009P-2EC V1.0 manual does not document this mode**. It
explicitly documents MIT, Position-Velocity and Velocity. Therefore this repo
exposes FORCE_POS for DM-J6248P but not for DM-J8009P-2EC.

## State commands

DaMiao protocol uses:

```text
Enable      FF FF FF FF FF FF FF FC
Disable     FF FF FF FF FF FF FF FD
Set zero    FF FF FF FF FF FF FF FE
Clear fault FF FF FF FF FF FF FF FB
```

## Control mode register

RID/register 10:

```text
1 = MIT
2 = POS_VEL
3 = VEL
4 = FORCE_POS
```

The previous repo backend hard-coded DM-J6248P as MIT and forced MIT again on
enable. That was protocol-correct for MIT but incomplete for this multi-mode
motor. The backend now reads/writes register 10 and does not silently force MIT
on enable.

## DM-J6248P verdict

Previous implementation:

- MIT frame packing: correct through the `damiao-motor` package
- model preset: correct (`6248P` => 12.566 / 20 / 120)
- enable/disable encoding: correct through the package
- supported modes: incomplete (MIT only)
- enable behavior: incorrect for non-MIT use because it forced MIT
- mode reporting: incomplete because it always returned `mit`

Updated implementation exposes MIT / POS_VEL / VEL / FORCE_POS.

## DM-J8009P-2EC integration

```text
repo key   = damiao_8009p
display    = DaMiao DM-J8009P-2EC
SDK preset = 8009
bitrate    = 1 Mbps
modes      = MIT / POS_VEL / VEL
```

The 12.5 / 45 / 54 MIT limits come from the DaMiao official SDK. The supplied
8-page J8009P V1.0 manual says P_MAX/V_MAX/T_MAX are configurable but does not
state these default numeric values, so the repo treats them as SDK-derived.

## Automatic scan limitation

Current `damiao-motor` feedback routing uses `logical_id = D[0] & 0x0F`.
Automatic discovery therefore cannot uniquely distinguish IDs above 15. The
repo deliberately scans logical Motor IDs 1..15 by default. This is a Python
dependency routing limitation, not a claimed motor-hardware ID limit.

## CAN FD boundary

DaMiao provides separate CAN-FD SDK examples for some products, but this repo's
DaMiao integration remains on Classic CAN for these backends. The supplied
J8009P V1.0 manual specifically documents standard CAN at 1 Mbps.
