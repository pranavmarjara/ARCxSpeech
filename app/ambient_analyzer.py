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

    # ==========================================
    # Recording Quality Classification
    # ==========================================

    quality_score = 100

    mean_rms = float(np.mean(rms))
    mean_flatness = float(np.mean(flatness))

    if mean_rms > 0.10:
        quality_score -= 40

    elif mean_rms > 0.05:
        quality_score -= 25

    elif mean_rms > 0.02:
        quality_score -= 10


    if peak > 0.50:
        quality_score -= 20

    elif peak > 0.30:
        quality_score -= 10


    if mean_flatness > 0.40:
        quality_score -= 20

    elif mean_flatness > 0.25:
        quality_score -= 10


    quality_score = max(0, min(100, quality_score))


    if quality_score >= 90:

        rating = "★★★★★"

        environment = "Excellent Recording Environment"

        recommendation = (
            "Suitable for clinical speech assessment."
        )

    elif quality_score >= 75:

        rating = "★★★★☆"

        environment = "Good Recording Environment"

        recommendation = (
            "Low ambient noise detected."
        )

    elif quality_score >= 60:

        rating = "★★★☆☆"

        environment = "Moderate Ambient Noise"

        recommendation = (
            "Recording is acceptable, but a quieter environment is recommended."
        )

    elif quality_score >= 40:

        rating = "★★☆☆☆"

        environment = "High Ambient Noise"

        recommendation = (
            "Some speech measurements may be affected."
        )

    else:

        rating = "★☆☆☆☆"

        environment = "Poor Recording Environment"

        recommendation = (
            "Test results should be interpreted with caution due to elevated environmental noise."
        )


    metrics["Recording Quality"] = rating

    metrics["Quality Score"] = quality_score

    metrics["Environment"] = environment

    metrics["Recommendation"] = recommendation

    return metrics