import librosa
import numpy as np
import parselmouth

from app.config import (
    PATIENT_CHANNEL,
    AMBIENT_CHANNEL
)

from scipy.signal import find_peaks


# =====================================
# LOAD AUDIO
# =====================================

def load_audio(filepath):

    # filepath now points at the isolated patient-audio mono WAV
    # written by recorder.py (recordings/patient_audio/...) -- no
    # more stereo channel splitting needed here.
    audio, sr = librosa.load(
        filepath,
        sr=None,
        mono=False
    )

    if audio.ndim == 1:

        patient_audio = audio

    else:

        # Defensive fallback in case a stereo file is ever passed in
        # (e.g. an old pre-split recording).
        patient_audio = audio[PATIENT_CHANNEL]

    # ambient_audio is no longer read from this file; kept as a zero
    # array so the 5-value return signature (and every caller that
    # unpacks it) doesn't need to change.
    ambient_audio = np.zeros_like(patient_audio)

    duration = librosa.get_duration(
        y=patient_audio,
        sr=sr
    )

    patient_sound = parselmouth.Sound(
        patient_audio.astype(np.float64),
        sampling_frequency=sr
    )

    return (
        patient_audio,
        ambient_audio,
        sr,
        duration,
        patient_sound
    )


# =====================================
# SYLLABLE NUCLEI DETECTOR
#
# Intensity-peak method (based on de Jong & Wempe, 2009):
# 1. Find local intensity maxima above a dynamic silence threshold.
# 2. Merge peaks not separated by a sufficient intensity dip
#    (avoids double-counting a single syllable).
# 3. Keep only peaks landing on a voiced (pitched) frame.
# Used exclusively for Speech Rate. DDK Repetition Rate/Count uses
# the same dynamic-threshold + voicing-check principle, but as a
# separate detector tuned for DDK's faster repetition cadence
# (see _ddk_intensity_contour and extract_ddk_features below) --
# they're independently computed, not sharing state.
# =====================================

def count_syllable_nuclei(snd):

    silence_db = -25

    min_dip_db = 2

    intensity = snd.to_intensity(
        minimum_pitch=100.0
    )

    intensity_values = intensity.values[0]

    intensity_times = intensity.xs()

    if len(intensity_values) == 0:

        return 0

    max_intensity = np.max(
        intensity_values
    )

    max_99_intensity = np.percentile(
        intensity_values,
        99
    )

    threshold = max_99_intensity + silence_db

    threshold = max(
        threshold,
        np.min(intensity_values)
    )

    # Minimum spacing between candidate syllable peaks (~50ms),
    # guards against noise-driven micro-peaks inflating the count.

    if len(intensity_times) > 1:

        time_step = float(
            intensity_times[1] - intensity_times[0]
        )

    else:

        time_step = 0.01

    min_distance = max(
        int(0.05 / time_step),
        1
    )

    peak_indices, _ = find_peaks(
        intensity_values,
        height=threshold,
        distance=min_distance
    )

    if len(peak_indices) == 0:

        return 0

    # Merge candidate peaks that aren't separated by a big
    # enough intensity dip, keeping the stronger of the two.

    valid_peak_indices = [
        peak_indices[0]
    ]

    for idx in peak_indices[1:]:

        prev_idx = valid_peak_indices[-1]

        between = intensity_values[prev_idx:idx + 1]

        dip = np.min(between)

        separated = (
            (intensity_values[prev_idx] - dip) > min_dip_db
            or (intensity_values[idx] - dip) > min_dip_db
        )

        if separated:

            valid_peak_indices.append(idx)

        else:

            if intensity_values[idx] > intensity_values[prev_idx]:

                valid_peak_indices[-1] = idx

    # Voicing check: keep only peaks on voiced (pitched) frames,
    # to discard non-speech intensity bursts.

    pitch = snd.to_pitch(
        time_step=0.01,
        pitch_floor=75,
        pitch_ceiling=500
    )

    nsyll = 0

    for idx in valid_peak_indices:

        t = intensity_times[idx]

        f0_at_t = pitch.get_value_at_time(t)

        if not np.isnan(f0_at_t) and f0_at_t > 0:

            nsyll += 1

    return nsyll


# =====================================
# SUSTAINED VOWEL FEATURES
#
# Kept: F0 Mean, HNR (primary)
#       Jitter Local, F0 Min, F0 Max, F1 Mean, F2 Mean (secondary)
# =====================================

def extract_vowel_features(filepath):

    patient_audio, ambient_audio, sr, duration, snd = load_audio(
        filepath
    )

    # Downsample for pitch tracking

    y_16k = librosa.resample(
        patient_audio,    
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

        f0_min = float(
            np.min(f0_clean)
        )

        f0_max = float(
            np.max(f0_clean)
        )

    else:

        f0_mean = 0
        f0_min = 0
        f0_max = 0

    # -------------------------
    # PRAAT FEATURES
    # -------------------------

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

    # Praat returns local jitter as a raw fraction (e.g. 0.012).
    # Correct formula requires it expressed as a percentage:
    # (mean(|Ti - Ti-1|) / mean(T)) x 100
    jitter_local = jitter_local * 100

    vowel_metrics = {

        "F0 Mean": round(
            f0_mean,
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

        "F1 Mean": round(
            f1_mean,
            3
        ),

        "F2 Mean": round(
            f2_mean,
            3
        ),

        "HNR": round(
            hnr,
            3
        ),

        "Jitter Local": round(
            jitter_local,
            6
        )
    }

    return vowel_metrics


# =====================================
# DDK FEATURES
#
# Kept: DDK Repetition Rate, DDK Repetition Count, DDK Interval Mean,
#       DDK Regularity, Speech Rate, Pause/Speech Ratio (primary)
#       DDK Interval Std (secondary)
# =====================================

def _ddk_intensity_contour(snd, silence_db=-25):
    """
    Dynamic-threshold intensity contour for DDK repetition detection --
    same principle as count_syllable_nuclei's threshold (99th-percentile
    intensity - silence_db, floored at the recording's minimum), instead
    of a single global-mean amplitude threshold. This keeps DC offset
    or low-frequency noise from silently shifting where "speech" is
    drawn, and gives repetition peaks a voicing check to lean on.
    """

    

    intensity = snd.to_intensity(minimum_pitch=100.0)

    intensity_values = intensity.values[0]
    intensity_times = intensity.xs()

    if len(intensity_values) == 0:
        return snd, intensity_times, intensity_values, 0.0, 0.01

    max_99_intensity = np.percentile(intensity_values, 99)

    threshold = max_99_intensity + silence_db

    threshold = max(threshold, np.min(intensity_values))

    if len(intensity_times) > 1:
        time_step = float(intensity_times[1] - intensity_times[0])
    else:
        time_step = 0.01

    return snd, intensity_times, intensity_values, threshold, time_step

def extract_ddk_features(filepath):

    patient_audio, ambient_audio, sr, duration, snd = load_audio(
        filepath
    )

    snd, intensity_times, intensity_values, threshold, time_step = _ddk_intensity_contour(
        snd
    )

    if len(intensity_values) == 0:

        speech_time = 0.0
        pause_time = duration
        pause_ratio = 0

        repetition_count = 0
        repetition_rate = 0
        interval_mean = 0
        interval_std = 0
        ddk_regularity = 0

    else:

        speech_frames = intensity_values > threshold

        speech_time = float(np.sum(speech_frames)) * time_step

        pause_time = max(duration - speech_time, 0)

        if speech_time > 0:
            pause_ratio = pause_time / speech_time
        else:
            pause_ratio = 0

        # Minimum spacing between candidate DDK repetition peaks
        # (~120ms) -- fast enough not to merge genuine rapid
        # /pa-ta-ka/ repetitions, but still guards against
        # noise-driven micro-peaks inflating the count.
        min_distance = max(int(0.12 / time_step), 1)

        peak_indices, _ = find_peaks(
            intensity_values,
            height=threshold,
            distance=min_distance
        )

        # Voicing check: keep only peaks landing on a voiced (pitched)
        # frame, same principle as count_syllable_nuclei, so a mic
        # pop or breath burst can't be counted as a repetition.
        pitch = snd.to_pitch(
            time_step=0.01,
            pitch_floor=75,
            pitch_ceiling=500
        )

        valid_peak_times = []

        for idx in peak_indices:

            t = intensity_times[idx]

            f0_at_t = pitch.get_value_at_time(t)

            if not np.isnan(f0_at_t) and f0_at_t > 0:

                valid_peak_times.append(t)

        repetition_count = len(valid_peak_times)

        if repetition_count > 1:

            intervals = np.diff(valid_peak_times)

            repetition_rate = repetition_count / duration

            interval_mean = float(np.mean(intervals))
            interval_std = float(np.std(intervals))

            if interval_mean > 0:
                ddk_regularity = (interval_std / interval_mean) * 100
            else:
                ddk_regularity = 0

        else:

            repetition_rate = 0
            interval_mean = 0
            interval_std = 0
            ddk_regularity = 0

    # -------------------------
    # SPEECH RATE (independent of DDK repetition detection)
    # Speech Rate = number_of_syllables / total_speech_sample_duration_seconds
    # -------------------------

    syllable_count = count_syllable_nuclei(
        snd
    )

    if duration > 0:

        speech_rate = syllable_count / duration

    else:

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

        "Syllable Count": syllable_count,

        "Pause/Speech Ratio": round(
            pause_ratio,
            3
        ),

        "DDK Interval Std": round(
            interval_std,
            3
        )
    }

    return ddk_metrics
