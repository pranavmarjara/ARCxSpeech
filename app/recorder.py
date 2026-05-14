import sounddevice as sd
import soundfile as sf
import time
import os

from app.config import (
    SAMPLE_RATE,
    CHANNELS,
    DURATION,
    OUTPUT_DIR
)

os.makedirs(OUTPUT_DIR, exist_ok=True)


def record_audio():

    timestamp = int(time.time())

    filename = f"{OUTPUT_DIR}/clinical_{timestamp}.wav"

    print("\nRecording started...")

    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype='float32',
        blocking=True
    )

    print("Recording completed.")

    sf.write(
        filename,
        audio,
        SAMPLE_RATE,
        subtype='PCM_24'
    )

    return filename, audio