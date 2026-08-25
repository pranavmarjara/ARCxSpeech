import os
import time
import uuid
import serial
import numpy as np
import soundfile as sf

from app.config import (
    SAMPLE_RATE,
    CHANNELS,
    OUTPUT_DIR,
    PATIENT_AUDIO_DIR,
    AMBIENT_AUDIO_DIR,
    PATIENT_CHANNEL,
    AMBIENT_CHANNEL,
    SERIAL_PORT,
    SERIAL_BAUD
)

os.makedirs(
    PATIENT_AUDIO_DIR,
    exist_ok=True
)

os.makedirs(
    AMBIENT_AUDIO_DIR,
    exist_ok=True
)


class RecordingError(Exception):
    """Base class for recording failures, raised instead of hanging or
    letting a raw serial/hardware exception surface uncaught."""


class RecordingTimeoutError(RecordingError):
    """Raised when the serial link stalls (no bytes received) for
    longer than the allowed grace period, instead of looping forever."""


# How much longer than the expected recording duration we'll wait for
# a stalled link before giving up. Generous, since USB/serial buffering
# can lag behind real time, but bounded so a dead link can't hang the
# app forever.
STALL_GRACE_SECONDS = 10

# ADD:
import itertools

_trial_counter = itertools.count()


# ---------------------------------------------------------------------
# Serial pre-warming
# ---------------------------------------------------------------------
# Opening the serial port and letting the device settle (see
# _open_and_settle_serial below) takes ~2s. That settle step used to
# run *inside* record_audio(), after the timed capture request had
# already landed -- so actual sample reading (and therefore the audio
# itself) started ~2s after the caller's t=0, and, since a fixed
# number of samples is read from that later start point, it also
# finished ~2s after the caller's expected end (t=duration). The
# on-screen countdown/progress bar in the UI has no way to know about
# that lag, so it visually starts/ends ~2s ahead of when the
# microphone is actually capturing.
#
# Fix: let a caller open + settle the port *ahead of time* (e.g.
# during the UI's 3s pre-record countdown, well before the timed
# capture is requested), hand back a token for that already-warmed
# connection, and have record_audio() consume it and start reading
# bytes immediately instead of opening+sleeping first. That lines up
# real capture start with the caller's t=0 (and therefore real capture
# end with t=duration) instead of both drifting ~2s late.
PREPARE_SETTLE_SECONDS = 2

# How long a prepared-but-unused connection is kept around before it's
# discarded (closed) as stale, e.g. if the client warmed up the mic
# but never actually started a recording.
PREPARE_EXPIRY_SECONDS = 20

_prepared_connections = {}  # token -> (serial.Serial, expires_at_monotonic)


def _open_and_settle_serial():
    """Opens the serial port and waits for the device to settle,
    discarding whatever garbage it buffered while starting up. Returns
    an open, ready-to-read serial.Serial."""

    print("\nOpening serial port...")

    try:

        ser = serial.Serial(
            SERIAL_PORT,
            SERIAL_BAUD,
            timeout=5
        )

    except serial.SerialException as e:

        raise RecordingError(
            f"Could not open serial port {SERIAL_PORT}: {e}"
        ) from e

    try:

        time.sleep(PREPARE_SETTLE_SECONDS)

        ser.reset_input_buffer()

    except Exception:

        ser.close()
        raise

    return ser


def prepare_serial():
    """Opens + settles the serial connection ahead of a timed capture
    and stashes it under a token, so the settle delay can happen
    during the UI's pre-record countdown instead of after the timed
    capture request lands. Call record_audio(..., prepare_token=...)
    with the returned token to consume it."""

    ser = _open_and_settle_serial()

    token = uuid.uuid4().hex
    _prepared_connections[token] = (ser, time.monotonic() + PREPARE_EXPIRY_SECONDS)

    _evict_expired_prepared()

    return token


def _evict_expired_prepared():
    now = time.monotonic()
    for stale_token in [t for t, (_, exp) in _prepared_connections.items() if exp < now]:
        stale_ser, _ = _prepared_connections.pop(stale_token)
        try:
            stale_ser.close()
        except Exception:
            pass


def _take_prepared_serial(token):
    """Pops and returns the serial connection for `token` if it's
    still present and hasn't expired, else None."""

    if token is None:
        return None

    entry = _prepared_connections.pop(token, None)

    if entry is None:
        return None

    ser, expires_at = entry

    if time.monotonic() > expires_at:
        try:
            ser.close()
        except Exception:
            pass
        return None

    return ser


def release_prepared(token):
    """Closes and discards a prepared-but-never-used connection, e.g.
    when the user cancels the pre-record countdown. Without this the
    port would just sit open until PREPARE_EXPIRY_SECONDS passes,
    which could block a fast retry from reopening it."""

    ser = _take_prepared_serial(token)
    if ser is not None:
        try:
            ser.close()
        except Exception:
            pass


def record_audio(
    duration,
    prefix="clinical",
    prepare_token=None
):

    # REPLACEMENT:
    # Microsecond resolution + a process-local monotonic counter,
    # instead of whole-second time.time(): two trials completing in
    # the same wall-clock second (a fast retry after an error, or
    # simply unlucky timing) used to silently overwrite each other's
    # WAV file on disk with no warning.
    timestamp = int(time.time() * 1_000_000)

    trial_id = next(_trial_counter)

    patient_filename = (
        f"{PATIENT_AUDIO_DIR}/"
        f"{prefix}_patient_audio_{timestamp}_{trial_id}.wav"
    )

    ambient_filename = (
        f"{AMBIENT_AUDIO_DIR}/"
        f"{prefix}_ambient_audio_{timestamp}_{trial_id}.wav"
    )

    total_samples = int(
        SAMPLE_RATE * duration
    )

    total_int16_values = (
        total_samples *
        CHANNELS
    )

    total_bytes = (
        total_int16_values *
        2
    )

    # Reuse an already-open, already-settled connection if the caller
    # warmed one up ahead of time (see prepare_serial() above) -- this
    # is what keeps real capture start in sync with the caller's t=0.
    # Otherwise fall back to opening + settling right now, same as the
    # old behavior (used by callers -- batch scripts, etc. -- that
    # don't pre-warm).
    ser = _take_prepared_serial(prepare_token)
    if ser is None:
        ser = _open_and_settle_serial()

    try:

        print("Recording started...")

        raw = bytearray()

        recording_deadline = time.monotonic() + duration + STALL_GRACE_SECONDS
        last_data_time = time.monotonic()

        while len(raw) < total_bytes:

            remaining = total_bytes - len(raw)

            chunk = ser.read(
                min(
                    4096,
                    remaining
                )
            )

            now = time.monotonic()

            if len(chunk) == 0:

                if now - last_data_time > STALL_GRACE_SECONDS:

                    raise RecordingTimeoutError(
                        f"No data received from {SERIAL_PORT} for over "
                        f"{STALL_GRACE_SECONDS}s -- the device may have "
                        "disconnected or stopped streaming mid-recording. "
                        f"Received {len(raw)}/{total_bytes} bytes."
                    )

                if now > recording_deadline:

                    raise RecordingTimeoutError(
                        f"Recording did not complete within the expected "
                        f"time ({duration}s + {STALL_GRACE_SECONDS}s grace). "
                        f"Received {len(raw)}/{total_bytes} bytes."
                    )

                continue

            last_data_time = now
            raw.extend(chunk)

        print("Recording completed.")

    finally:

        ser.close()

    audio = np.frombuffer(
        raw,
        dtype=np.int16
    )

    audio = audio.reshape(
        (-1, CHANNELS)
    )

    # REPLACEMENT:
    audio = (
        audio.astype(np.float32)
        / 32768.0
    )

    # Catch a dead/disconnected mic at the moment of recording instead
    # of only finding out later, downstream, when the Recording Quality
    # gate flags near-silence after all 6 trials are already done. This
    # is the same failure mode as the all-zero I2S readout bug from
    # hardware bringup -- this doesn't prevent a regression, but it
    # surfaces it immediately instead of silently saving a dead file.
    peak_per_channel = np.max(np.abs(audio), axis=0)

    if np.all(peak_per_channel < 0.001):

        print(
            "\nWARNING: recorded audio is near-silent on all channels "
            f"(peak={peak_per_channel}). Check microphone connections "
            "before using this trial."
        )

    patient_audio = audio[:, PATIENT_CHANNEL]
    ambient_audio = audio[:, AMBIENT_CHANNEL]

    sf.write(
        patient_filename,
        patient_audio,
        SAMPLE_RATE,
        subtype="PCM_16"
    )

    sf.write(
        ambient_filename,
        ambient_audio,
        SAMPLE_RATE,
        subtype="PCM_16"
    )

    return (
        patient_filename,
        ambient_filename,
        audio
    )