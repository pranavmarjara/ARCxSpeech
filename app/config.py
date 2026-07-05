SAMPLE_RATE = 48000
CHANNELS = 1

VOWEL_DURATION = 5
DDK_DURATION = 10

OUTPUT_DIR = "recordings"

# ============================================================
# Preprocessing pipeline -- Layers 1 & 2 (used by app/preprocessing.py
# and the R&D staged-extraction feature, which compares "No Layer",
# "1 Layer" and "2 Layers" for the same recording).
# ============================================================

# Layer 1: DC Offset Removal has no tunable parameters.

# Layer 2: Frequency Filtering
HIGHPASS_CUTOFF_HZ = 60
LOWPASS_CUTOFF_HZ = 7500
NOTCH_FREQ_HZ = 60
NOTCH_Q = 30