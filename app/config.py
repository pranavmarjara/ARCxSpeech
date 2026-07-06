# ===========================
# Audio Configuration
# ===========================

import os
import sys


def _detect_serial_port():
    """
    Picks a serial port cross-platform instead of hardcoding a
    Windows-only name like "COM8" (which doesn't exist on macOS/Linux).

    Resolution order:
      1. ARCXSPEECH_SERIAL_PORT env var, if set -- always wins, so a
         specific machine/device can be pinned without editing code.
      2. Auto-detect via pyserial's port listing -- picks the first
         connected serial device, which covers the common case of
         exactly one USB acquisition device plugged in.
      3. Platform-specific fallback guess, used only if neither of the
         above found anything (e.g. device not plugged in yet at
         import time). recorder.py already raises a clear
         RecordingError if this guess is wrong, so it's a safe default
         rather than a silent failure.
    """

    override = os.environ.get("ARCXSPEECH_SERIAL_PORT")

    if override:
        return override

    try:

        from serial.tools import list_ports

        ports = list(list_ports.comports())

        if ports:
            return ports[0].device

    except Exception:

        pass

    if sys.platform.startswith("win"):

        return "COM8"

    elif sys.platform == "darwin":

        return "/dev/cu.usbserial"

    else:

        return "/dev/ttyUSB0"


SAMPLE_RATE = 48000

CHANNELS = 2

BIT_DEPTH = 16

PATIENT_CHANNEL = 0

AMBIENT_CHANNEL = 1

SERIAL_PORT = _detect_serial_port()

SERIAL_BAUD = 2000000

VOWEL_DURATION = 5

DDK_DURATION = 10

OUTPUT_DIR = "recordings"

# ============================================================
# Preprocessing pipeline -- Layers 1 & 2 (used by app/preprocessing.py
# and the R&D staged-extraction feature, which compares "No Layer",
# "1 Layer" and "2 Layers" for the same recording).
# ============================================================

# Layer 1: DC Offset Removal has no tunable parameters.

# Layer 2: Frequency Filtering
HIGHPASS_CUTOFF_HZ = 60
LOWPASS_CUTOFF_HZ = 7500
NOTCH_FREQ_HZ = 60
NOTCH_Q = 30