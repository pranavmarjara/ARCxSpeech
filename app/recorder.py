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

    ser = serial.Serial(
        SERIAL_PORT,
        SERIAL_BAUD,
        timeout=5
    )

    time.sleep(2)

    ser.reset_input_buffer()

    print("Recording started...")

    raw = bytearray()

    while len(raw) < total_bytes:

        remaining = total_bytes - len(raw)

        chunk = ser.read(
            min(
                4096,
                remaining
            )
        )

        if len(chunk) == 0:
            continue

        raw.extend(chunk)

    ser.close()

    print("Recording completed.")

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