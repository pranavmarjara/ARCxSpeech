import os
import time
import serial
import numpy as np
import soundfile as sf

from app.config import (
    SAMPLE_RATE,
    CHANNELS,
    OUTPUT_DIR,
    SERIAL_PORT,
    SERIAL_BAUD
)

os.makedirs(
    OUTPUT_DIR,
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


def record_audio(
    duration,
    prefix="clinical"
):

    timestamp = int(time.time())

    filename = (
        f"{OUTPUT_DIR}/"
        f"{prefix}_{timestamp}.wav"
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

    audio = (
        audio.astype(np.float32)
        / 32768.0
    )

    sf.write(
        filename,
        audio,
        SAMPLE_RATE,
        subtype="PCM_16"
    )

    return (
        filename,
        audio
    )