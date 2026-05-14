from app.recorder import record_audio
from app.verifier import verify_audio

print("\nARC Clinical Speech")
print("----------------------------")

filepath, audio = record_audio()

verify_audio(filepath)

print(f"\nSaved File: {filepath}")