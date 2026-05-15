import librosa
import numpy as np
import parselmouth

from scipy.signal import find_peaks


# =====================================
# LOAD AUDIO
# =====================================

def load_audio(filepath):

    y, sr = librosa.load(
        filepath,
        sr=None
    )

    duration = librosa.get_duration(
        y=y,
        sr=sr
    )

    return y, sr, duration


# =====================================
# COMMON FEATURES
# =====================================

def extract_common_features(y, sr, duration):

    rms = librosa.feature.rms(y=y)[0]

    zcr = librosa.feature.zero_crossing_rate(y)[0]

    centroid = librosa.feature.spectral_centroid(
        y=y,
        sr=sr
    )[0]

    rolloff = librosa.feature.spectral_rolloff(
        y=y,
        sr=sr
    )[0]

    return {

        "Sample Rate": sr,

        "Duration (sec)": round(
            duration,
            3
        ),

        "RMS Mean": round(
            float(np.mean(rms)),
            6
        ),

        "RMS Std": round(
            float(np.std(rms)),
            6
        ),

        "ZCR Mean": round(
            float(np.mean(zcr)),
            6
        ),

        "Spectral Centroid": round(
            float(np.mean(centroid)),
            3
        ),

        "Spectral Rolloff": round(
            float(np.mean(rolloff)),
            3
        )
    }


# =====================================
# SUSTAINED VOWEL FEATURES
# =====================================

def extract_vowel_features(filepath):

    y, sr, duration = load_audio(
        filepath
    )

    common = extract_common_features(
        y,
        sr,
        duration
    )

    # Downsample for pitch tracking

    y_16k = librosa.resample(
        y,
        orig_sr=sr,
        target_sr=16000
    )

    # -------------------------
    # F0
    # -------------------------

    f0, voiced_flag, voiced_probs = librosa.pyin(
        y_16k,
        fmin=50,
        fmax=500,
        sr=16000
    )

    f0_clean = f0[
        ~np.isnan(f0)
    ]

    if len(f0_clean) > 0:

        f0_mean = float(
            np.mean(f0_clean)
        )

        f0_std = float(
            np.std(f0_clean)
        )

        f0_min = float(
            np.min(f0_clean)
        )

        f0_max = float(
            np.max(f0_clean)
        )

    else:

        f0_mean = 0
        f0_std = 0
        f0_min = 0
        f0_max = 0

    # -------------------------
    # PRAAT FEATURES
    # -------------------------

    snd = parselmouth.Sound(
        filepath
    )

    harmonicity = snd.to_harmonicity()

    harmonicity_values = harmonicity.values[
        harmonicity.values != -200
    ]

    if len(harmonicity_values) > 0:

        hnr = float(
            np.mean(harmonicity_values)
        )

    else:

        hnr = 0

    point_process = parselmouth.praat.call(
        snd,
        "To PointProcess (periodic, cc)",
        75,
        500
    )

    jitter_local = parselmouth.praat.call(
        point_process,
        "Get jitter (local)",
        0,
        0,
        0.0001,
        0.02,
        1.3
    )

    shimmer_local = parselmouth.praat.call(
        [snd, point_process],
        "Get shimmer (local)",
        0,
        0,
        0.0001,
        0.02,
        1.3,
        1.6
    )

    vowel_metrics = {

        "F0 Mean": round(
            f0_mean,
            3
        ),

        "F0 Std": round(
            f0_std,
            3
        ),

        "F0 Min": round(
            f0_min,
            3
        ),

        "F0 Max": round(
            f0_max,
            3
        ),

        "HNR": round(
            hnr,
            3
        ),

        "Jitter Local": round(
            jitter_local,
            6
        ),

        "Shimmer Local": round(
            shimmer_local,
            6
        )
    }

    return {
        **common,
        **vowel_metrics
    }


# =====================================
# DDK FEATURES
# =====================================

def extract_ddk_features(filepath):

    y, sr, duration = load_audio(
        filepath
    )

    common = extract_common_features(
        y,
        sr,
        duration
    )

    y_16k = librosa.resample(
        y,
        orig_sr=sr,
        target_sr=16000
    )

    envelope = np.abs(
        y_16k
    )

    peaks, _ = find_peaks(
        envelope,
        distance=16000 // 4,
        height=np.mean(envelope)
    )

    repetition_count = len(peaks)

    if repetition_count > 1:

        intervals = np.diff(peaks) / 16000

        repetition_rate = (
            repetition_count / duration
        )

        interval_mean = float(
            np.mean(intervals)
        )

        interval_std = float(
            np.std(intervals)
        )

    else:

        repetition_rate = 0
        interval_mean = 0
        interval_std = 0

    ddk_metrics = {

        "DDK Repetition Count": repetition_count,

        "DDK Repetition Rate": round(
            repetition_rate,
            3
        ),

        "DDK Interval Mean": round(
            interval_mean,
            3
        ),

        "DDK Interval Std": round(
            interval_std,
            3
        )
    }

    return {
        **common,
        **ddk_metrics
    }