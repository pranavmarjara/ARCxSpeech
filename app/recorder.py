import os
import time
import serial
import numpy as np
import soundfile as sf

from app.config import (
    SAMPLE_RATE,
    CHANNELS,
    OUTPUT_DIR,
    PATIENT_AUDIO_DIR,
    AMBIENT_AUDIO_DIR,
    PATIENT_CHANNEL,
    AMBIENT_CHANNEL,
    SERIAL_PORT,
    SERIAL_BAUD
)

os.makedirs(
    PATIENT_AUDIO_DIR,
    exist_ok=True
)

os.makedirs(
    AMBIENT_AUDIO_DIR,
    exist_ok=True
)


class RecordingError(Exception):
    """Base class for recording failures, raised instead of hanging or
    letting a raw serial/hardware exception surface uncaught."""


class RecordingTimeoutError(RecordingError):
    """Raised when the serial link stalls (no bytes received) for
    longer than the allowed grace period, instead of looping forever."""


# How much longer than the expected recording duration we'll wait for
# a stalled link before giving up. Generous, since USB/serial buffering
# can lag behind real time, but bounded so a dead link can't hang the
# app forever.
STALL_GRACE_SECONDS = 10

# ADD:
import itertools

_trial_counter = itertools.count()

def record_audio(
    duration,
    prefix="clinical"
):

    # REPLACEMENT:
    # Microsecond resolution + a process-local monotonic counter,
    # instead of whole-second time.time(): two trials completing in
    # the same wall-clock second (a fast retry after an error, or
    # simply unlucky timing) used to silently overwrite each other's
    # WAV file on disk with no warning.
    timestamp = int(time.time() * 1_000_000)

    trial_id = next(_trial_counter)

    patient_filename = (
        f"{PATIENT_AUDIO_DIR}/"
        f"{prefix}_patient_audio_{timestamp}_{trial_id}.wav"
    )

    ambient_filename = (
        f"{AMBIENT_AUDIO_DIR}/"
        f"{prefix}_ambient_audio_{timestamp}_{trial_id}.wav"
    )

    total_samples = int(
        SAMPLE_RATE * duration
    )

    total_int16_values = (
        total_samples *
        CHANNELS
    )

    total_bytes = (
        total_int16_values *
        2
    )

    print("\nOpening serial port...")

    try:

        ser = serial.Serial(
            SERIAL_PORT,
            SERIAL_BAUD,
            timeout=5
        )

    except serial.SerialException as e:

        raise RecordingError(
            f"Could not open serial port {SERIAL_PORT}: {e}"
        ) from e

    try:

        time.sleep(2)

        ser.reset_input_buffer()

        print("Recording started...")

        raw = bytearray()

        recording_deadline = time.monotonic() + duration + STALL_GRACE_SECONDS
        last_data_time = time.monotonic()

        while len(raw) < total_bytes:

            remaining = total_bytes - len(raw)

            chunk = ser.read(
                min(
                    4096,
                    remaining
                )
            )

            now = time.monotonic()

            if len(chunk) == 0:

                if now - last_data_time > STALL_GRACE_SECONDS:

                    raise RecordingTimeoutError(
                        f"No data received from {SERIAL_PORT} for over "
                        f"{STALL_GRACE_SECONDS}s -- the device may have "
                        "disconnected or stopped streaming mid-recording. "
                        f"Received {len(raw)}/{total_bytes} bytes."
                    )

                if now > recording_deadline:

                    raise RecordingTimeoutError(
                        f"Recording did not complete within the expected "
                        f"time ({duration}s + {STALL_GRACE_SECONDS}s grace). "
                        f"Received {len(raw)}/{total_bytes} bytes."
                    )

                continue

            last_data_time = now
            raw.extend(chunk)

        print("Recording completed.")

    finally:

        ser.close()

    audio = np.frombuffer(
        raw,
        dtype=np.int16
    )

    audio = audio.reshape(
        (-1, CHANNELS)
    )

    # REPLACEMENT:
    audio = (
        audio.astype(np.float32)
        / 32768.0
    )

    # Catch a dead/disconnected mic at the moment of recording instead
    # of only finding out later, downstream, when the Recording Quality
    # gate flags near-silence after all 6 trials are already done. This
    # is the same failure mode as the all-zero I2S readout bug from
    # hardware bringup -- this doesn't prevent a regression, but it
    # surfaces it immediately instead of silently saving a dead file.
    peak_per_channel = np.max(np.abs(audio), axis=0)

    if np.all(peak_per_channel < 0.001):

        print(
            "\nWARNING: recorded audio is near-silent on all channels "
            f"(peak={peak_per_channel}). Check microphone connections "
            "before using this trial."
        )

    patient_audio = audio[:, PATIENT_CHANNEL]
    ambient_audio = audio[:, AMBIENT_CHANNEL]

    sf.write(
        patient_filename,
        patient_audio,
        SAMPLE_RATE,
        subtype="PCM_16"
    )

    sf.write(
        ambient_filename,
        ambient_audio,
        SAMPLE_RATE,
        subtype="PCM_16"
    )

    return (
        patient_filename,
        ambient_filename,
        audio
    )