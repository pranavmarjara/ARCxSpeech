import numpy as np
import soundfile as sf
import hashlib


def verify_audio(filepath):

    data, sr = sf.read(filepath)

    peak = np.max(np.abs(data))

    clipping = peak >= 0.999

    with open(filepath, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print("\nVerification")
    print("------------------------")
    print(f"Sample Rate : {sr}")
    print(f"Duration    : {len(data)/sr:.2f} sec")
    print(f"Peak        : {peak:.6f}")
    print(f"Clipping    : {clipping}")
    print(f"SHA256      : {sha256}")

    return {
        "sample_rate": sr,
        "duration": len(data)/sr,
        "peak": peak,
        "clipping": clipping,
        "sha256": sha256
    }