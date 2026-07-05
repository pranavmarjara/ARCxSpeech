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

    return out.astype(audio.dtype)
