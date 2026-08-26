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
      2. Match by the board's known USB VID:PID (2886:0056) --
         identifies the actual acquisition device regardless of which
         COM number Windows assigns it or what else is plugged in
         (e.g. Bluetooth virtual COM ports have no VID/PID and would
         never match).
      3. Platform-specific fallback guess, used only if neither of the
         above found anything (e.g. device not plugged in yet at
         import time). recorder.py already raises a clear
         RecordingError if this guess is wrong, so it's a safe default
         rather than a silent failure.
    """

    override = os.environ.get("ARCXSPEECH_SERIAL_PORT")

    if override:
        return override

    BOARD_VID = 0x2886
    BOARD_PID = 0x0056

    try:

        from serial.tools import list_ports

        ports = list(list_ports.comports())

        for p in ports:

            if p.vid == BOARD_VID and p.pid == BOARD_PID:
                return p.device

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

# Absolute, anchored to this file's own location (ARCxSpeech-main/app/ ->
# ARCxSpeech-main/) rather than a relative path off the process's current
# working directory. A relative "recordings" here meant launching the app
# from a different folder silently created a brand new, empty
# recordings/patient_audio + ambient_audio pair there instead of using the
# real one -- this pins it to always resolve to the same place regardless
# of where main.py is invoked from.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(_BASE_DIR, "recordings")

PATIENT_AUDIO_DIR = os.path.join(OUTPUT_DIR, "patient_audio")

AMBIENT_AUDIO_DIR = os.path.join(OUTPUT_DIR, "ambient_audio")

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