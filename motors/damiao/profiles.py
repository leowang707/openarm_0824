"""Documented Classic profile and an explicitly unverified FD candidate."""
from can_profiles import BusProfile

CLASSIC_1M = BusProfile(
    key="classic_1m", label="Classic CAN 1 Mbps", fd=False,
    nominal_bitrate=1_000_000, protocol_key="damiao_classic",
    notes="Classic integration from the supplied manual and dependency; confirm device configuration.",
)

# Kept for compatibility with the local B-stage key; NOT a proven hardware profile.
J8009_CANFD_1M_5M_OBSERVED = BusProfile(
    key="canfd_1m_5m", label="CAN-FD 1M / 5M candidate (unverified)",
    fd=True, nominal_bitrate=1_000_000, data_bitrate=5_000_000,
    implemented=False, evidence="candidate_not_hardware_verified",
    protocol_key="damiao_canfd_unverified",
    notes=("UART on one J8009-series unit reports 5.00Mbps only. "
           "1M/5M is an official SDK example, not a measurement of this unit. "
           "FD framing, BRS, firmware compatibility and exact model remain unverified."),
)
