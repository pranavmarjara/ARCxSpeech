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

    formant = snd.to_formant_burg()

    times = formant.ts()

    f1_values = []

    f2_values = []

    for t in times:

        f1 = formant.get_value_at_time(
            1,
            t
        )

        f2 = formant.get_value_at_time(
            2,
            t
        )

        if not np.isnan(f1):

            f1_values.append(
                f1
            )

        if not np.isnan(f2):

            f2_values.append(
                f2
            )


    if len(f1_values) > 0:

        f1_mean = float(
            np.mean(
                f1_values
            )
        )

    else:

        f1_mean = 0


    if len(f2_values) > 0:

        f2_mean = float(
            np.mean(
                f2_values
            )
        )

    else:

        f2_mean = 0

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

    f0_range = f0_max - f0_min

    pitch_variability = f0_std

    intensity_variability = float(
        np.std(
            librosa.feature.rms(
                y=y
            )[0]
        )
    )

    

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

        "F0 Range": round(
            f0_range,
            3
        ),

        "Pitch Variability": round(
            pitch_variability,
            3
        ),

        "Intensity Variability": round(
            intensity_variability,
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

    threshold = np.mean(
        envelope
    )

    speech_frames = (
        envelope > threshold
    )

    speech_time = (
        np.sum(
            speech_frames
        ) / 16000
    )

    pause_time = max(
        duration - speech_time,
        0
    )

    if speech_time > 0:

        pause_ratio = (
            pause_time /
            speech_time
        )

    else:

        pause_ratio = 0


    pause_segments = []

    in_pause = False

    pause_start = 0

    for i, frame in enumerate(
        speech_frames
    ):

        if not frame and not in_pause:

            pause_start = i

            in_pause = True

        elif frame and in_pause:

            pause_segments.append(
                (
                    i - pause_start
                ) / 16000
            )

            in_pause = False


    if len(pause_segments) > 0:

        mean_pause_duration = float(
            np.mean(
                pause_segments
            )
        )

    else:

        mean_pause_duration = 0

    peaks, _ = find_peaks(
        envelope,
        distance=16000 // 4,
        height=np.mean(envelope)
    )

    repetition_count = len(peaks)

    if repetition_count > 1:

        intervals = np.diff(
            peaks
        ) / 16000

        repetition_rate = (
            repetition_count / duration
        )

        interval_mean = float(
            np.mean(intervals)
        )

        interval_std = float(
            np.std(intervals)
        )

        ddk_regularity = interval_std

        speech_rate = repetition_rate

    else:

        repetition_rate = 0

        interval_mean = 0

        interval_std = 0

        ddk_regularity = 0

        speech_rate = 0

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

        "DDK Regularity": round(
            ddk_regularity,
            3
        ),

        "Speech Rate": round(
            speech_rate,
            3
        ),

        "Mean Pause Duration": round(
            mean_pause_duration,
            3
        ),

        "Pause/Speech Ratio": round(
            pause_ratio,
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