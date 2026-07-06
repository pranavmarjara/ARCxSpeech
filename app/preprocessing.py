import warnings

import numpy as np
from scipy import signal

from app.config import (
    SAMPLE_RATE,
    HIGHPASS_CUTOFF_HZ,
    LOWPASS_CUTOFF_HZ,
    NOTCH_FREQ_HZ,
    NOTCH_Q,
)


# ============================================================
# Layer 1: DC Offset Removal
# ============================================================
# Purpose:
#   Remove electronic signal bias (DC offset) introduced by the
#   microphone/ADC hardware.
#
# Validation:
#   Compare F0 / Jitter / Shimmer / HNR before vs after.
#   Pass -> minimal biomarker movement. Fail -> large changes.
# ============================================================
def remove_dc_offset(audio: np.ndarray) -> np.ndarray:
    offset = np.mean(audio, axis=0)
    return audio - offset


# ============================================================
# Layer 2: Frequency Filtering
# ============================================================
# Purpose:
#   Remove non-speech frequencies (sub-bass rumble, high-frequency
#   hiss, electrical mains hum) via high-pass, low-pass, and notch
#   filters.
#
# Validation:
#   Must preserve pitch, harmonics, formants, and voice quality.
#   Cutoffs are conservative and sit outside the speech-relevant
#   band so they should not be affected.
# ============================================================
def apply_frequency_filtering(audio: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    nyq = sr / 2.0
    out = audio.astype(np.float64)

    # High-pass: removes rumble / handling noise below speech range
    b, a = signal.butter(4, HIGHPASS_CUTOFF_HZ / nyq, btype="highpass", output="ba")
    out = signal.filtfilt(b, a, out, axis=0)

    # Low-pass: removes hiss above speech-relevant range
    b, a = signal.butter(4, LOWPASS_CUTOFF_HZ / nyq, btype="lowpass", output="ba")
    out = signal.filtfilt(b, a, out, axis=0)

    # Notch: removes electrical mains hum
    w0 = NOTCH_FREQ_HZ / nyq
    b, a = signal.iirnotch(w0, NOTCH_Q)
    out = signal.filtfilt(b, a, out, axis=0)

    # Cascaded filtfilt passes can produce transient overshoot/ringing
    # near band edges, so a near-full-scale input can exceed the
    # original dtype's range after filtering. Casting an out-of-range
    # float straight to an integer dtype does NOT clip -- it wraps
    # around silently (e.g. a value just above int16 max becomes a
    # large-magnitude value near int16 min), which looks like plausible
    # audio but is actually corrupted data. Clip explicitly first so the
    # cast always saturates instead of wrapping.
    if np.issubdtype(audio.dtype, np.integer):

        info = np.iinfo(audio.dtype)
        clipped = np.clip(out, info.min, info.max)

    else:

        # This codebase's convention is normalized float audio in
        # [-1.0, 1.0] (see recorder.py). Clip to that range so a
        # downstream PCM_16 write (soundfile) saturates predictably
        # instead of clipping unpredictably at write time.
        clipped = np.clip(out, -1.0, 1.0)

    num_clipped = int(np.sum(clipped != out))

    if num_clipped > 0:

        warnings.warn(
            f"apply_frequency_filtering: {num_clipped} sample(s) "
            "exceeded the valid range after filtering and were clipped "
            "to avoid integer wraparound / out-of-range floats. This "
            "usually means the input was recorded too close to full "
            "scale -- consider reducing input gain.",
            RuntimeWarning
        )

    return clipped.astype(audio.dtype)
