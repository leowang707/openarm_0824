"""DaMiao Classic-CAN mode names and current discovery bounds."""

MODE_TO_DRIVER = {
    "mit": "MIT",
    "pos_vel": "POS_VEL",
    "vel": "VEL",
    "force_pos": "FORCE_POS",
}

REGISTER_TO_MODE = {
    1: "mit",
    2: "pos_vel",
    3: "vel",
    4: "force_pos",
}

# damiao-motor currently routes feedback by the low 4 bits of D[0].
# Automatic discovery is therefore limited to logical IDs 1..15 so aliases
# such as 0x01 vs 0x11 cannot be silently misidentified.
SCAN_ID_MIN = 0x01
SCAN_ID_MAX = 0x0F
