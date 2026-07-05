import librosa
import numpy as np

from app.config import (
    AMBIENT_CHANNEL
)


def extract_ambient_metrics(filepath):

    audio, sr = librosa.load(
        filepath,
        sr=None,
        mono=False
    )

    if audio.ndim == 1:

        ambient = np.zeros_like(audio)

    else:

        ambient = audio[AMBIENT_CHANNEL]

    rms = librosa.feature.rms(
        y=ambient
    )[0]

    centroid = librosa.feature.spectral_centroid(
        y=ambient,
        sr=sr
    )[0]

    flatness = librosa.feature.spectral_flatness(
        y=ambient
    )[0]

    peak = np.max(
        np.abs(ambient)
    )

    noise_floor = np.percentile(
        np.abs(ambient),
        10
    )

    metrics = {

        "Ambient RMS":
            round(
                float(np.mean(rms)),
                6
            ),

        "Ambient Peak":
            round(
                float(peak),
                6
            ),

        "Noise Floor":
            round(
                float(noise_floor),
                6
            ),

        "Spectral Centroid":
            round(
                float(np.mean(centroid)),
                3
            ),

        "Spectral Flatness":
            round(
                float(np.mean(flatness)),
                6
            )
    }

    return metrics