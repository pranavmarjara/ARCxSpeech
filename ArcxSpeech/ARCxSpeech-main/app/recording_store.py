import json
import os
import tempfile
import uuid
from datetime import datetime
from typing import List

APP_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

RECORDINGS_FILE = os.path.join(APP_ROOT, "recordings.json")


def _atomic_write_json(filepath, data):
    """
    Writes JSON to `filepath` atomically: data is written to a temp file
    in the same directory, flushed to disk, then moved into place with
    os.replace (atomic on both POSIX and Windows). This means a crash or
    power loss mid-write can never leave `filepath` truncated or corrupt --
    either the old file is intact, or the new one is.

    Same pattern as app/subject_store.py and app/session_store.py -- kept
    as its own copy here so recording_store has no dependency on the
    other stores at all.
    """

    directory = os.path.dirname(filepath) or "."

    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=".tmp_",
        suffix=".json"
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, filepath)

    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_recordings():
    if not os.path.exists(RECORDINGS_FILE):
        _atomic_write_json(RECORDINGS_FILE, [])

    try:
        with open(RECORDINGS_FILE, "r") as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Recording data file at {RECORDINGS_FILE} is corrupted and "
            f"could not be read ({e}). No data was modified. Restore "
            "from a backup before continuing, since this file holds "
            "every recording in the study."
        ) from e


def get_recordings_for_session(session_id):
    recordings = load_recordings()
    return [r for r in recordings if r.get("session_id") == session_id]


def get_recordings_for_session_task(session_id, task):
    return [
        r for r in get_recordings_for_session(session_id)
        if r.get("task") == task
    ]


def get_recording(recording_id):
    recordings = load_recordings()
    return next(
        (r for r in recordings if r.get("recording_id") == recording_id),
        None
    )


def add_recording(
    session_id,
    task,
    source,
    patient_filepath,
    features,
    ambient_filepath=None,
    ambient_metrics=None,
    quality_metrics=None,
    quality_classification=None,
):
    """Appends ONE recording row. Callable any number of times, at any
    point after the session exists -- this is what lets recordings be
    added to a session whenever, instead of only at session-creation
    time. `source` is "live" or "uploaded"."""

    recordings = load_recordings()

    recording = {
        "recording_id": str(uuid.uuid4()),
        "session_id": session_id,
        "task": task,
        "source": source or "live",
        "created_at": datetime.now().isoformat(),
        "patient_filepath": patient_filepath,
        "ambient_filepath": ambient_filepath,
        "features": features or {},
        "ambient_metrics": ambient_metrics,
        "quality_metrics": quality_metrics,
        "quality_classification": quality_classification,
    }

    recordings.append(recording)
    _atomic_write_json(RECORDINGS_FILE, recordings)

    return recording


def update_recording_features(recording_id, features):
    """Patches just the `features` dict on an existing recording row --
    used by the deferred extraction flow (POST
    /api/sessions/{id}/recordings/extract), which logs a recording with
    features={} at capture time and fills them in later, in a batch,
    once the user taps "Extract Features". Returns the updated row, or
    None if recording_id didn't exist."""

    recordings = load_recordings()
    target = None
    for r in recordings:
        if r.get("recording_id") == recording_id:
            r["features"] = features
            target = r
            break

    if target is None:
        return None

    _atomic_write_json(RECORDINGS_FILE, recordings)
    return target


def delete_recording(recording_id):
    """Removes the recording row only. Returns the deleted row (so the
    caller -- api/routes.py -- can decide whether its file should be
    removed from disk, e.g. via the existing
    _delete_unreferenced_recordings pattern), or None if recording_id
    didn't exist."""

    recordings = load_recordings()
    target = next(
        (r for r in recordings if r.get("recording_id") == recording_id),
        None
    )

    if target is None:
        return None

    remaining = [r for r in recordings if r.get("recording_id") != recording_id]
    _atomic_write_json(RECORDINGS_FILE, remaining)

    return target


def delete_recordings_for_session(session_id):
    """Removes every recording row belonging to a session (used when a
    whole session is deleted). Returns the list of deleted rows so the
    caller can clean up their files on disk."""

    recordings = load_recordings()
    to_delete = [r for r in recordings if r.get("session_id") == session_id]

    if not to_delete:
        return []

    remaining = [r for r in recordings if r.get("session_id") != session_id]
    _atomic_write_json(RECORDINGS_FILE, remaining)

    return to_delete


def _compute_mean(feature_dicts: List[dict]) -> dict:
    """Same logic as the _compute_mean() currently in api/routes.py --
    only averages numeric values, rounds to 3 decimal places."""
    if not feature_dicts:
        return {}
    result = {}
    for key in feature_dicts[0].keys():
        values = [d[key] for d in feature_dicts if isinstance(d.get(key), (int, float))]
        if values:
            result[key] = round(sum(values) / len(values), 3)
    return result


def _compute_sd(feature_dicts: List[dict]) -> dict:
    """Same logic as the _compute_sd() currently in api/routes.py --
    needs at least 2 values per key to produce a standard deviation."""
    if len(feature_dicts) < 2:
        return {}
    result = {}
    for key in feature_dicts[0].keys():
        values = [d[key] for d in feature_dicts if isinstance(d.get(key), (int, float))]
        if len(values) > 1:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            result[key] = round(variance ** 0.5, 3)
    return result


def compute_session_summary(session_id):
    """Builds an Assessment-shaped summary for a session ON READ, from
    whatever recordings currently belong to it -- this replaces the old
    assessment_store.py blob that was written once and never updated.
    Add a recording tomorrow and the next call to this function reflects
    it automatically.

    Ambient/quality fields are only ever populated for "live" recordings
    that actually carried that data (see the open question in the
    handoff doc about what the live-recording endpoint records) --
    uploaded recordings leave them as None, same as the old upload path.
    """

    vowel_recs = get_recordings_for_session_task(session_id, "Sustained Vowel")
    ddk_recs = get_recordings_for_session_task(session_id, "DDK")

    vowel_trials = [r["features"] for r in vowel_recs]
    ddk_trials = [r["features"] for r in ddk_recs]

    ambient_metrics_all = [
        r["ambient_metrics"] for r in (vowel_recs + ddk_recs)
        if r.get("ambient_metrics")
    ]
    quality_metrics_all = [
        r["quality_metrics"] for r in (vowel_recs + ddk_recs)
        if r.get("quality_metrics")
    ]

    return {
        "session_id": session_id,
        "vowel_trials": vowel_trials,
        "vowel_mean": _compute_mean(vowel_trials),
        "vowel_sd": _compute_sd(vowel_trials),
        "vowel_recordings": [r["patient_filepath"] for r in vowel_recs],
        "ddk_trials": ddk_trials,
        "ddk_mean": _compute_mean(ddk_trials),
        "ddk_sd": _compute_sd(ddk_trials),
        "ddk_recordings": [r["patient_filepath"] for r in ddk_recs],
        "ambient_mean": _compute_mean(ambient_metrics_all),
        "ambient_sd": _compute_sd(ambient_metrics_all),
        "recording_quality_mean": _compute_mean(quality_metrics_all),
        "recording_quality_sd": _compute_sd(quality_metrics_all),
    }


def compute_subject_summary(subject_id, session_ids):
    """Same Assessment-shaped summary as compute_session_summary, but
    aggregated across every recording in every one of the subject's
    sessions (session_ids), rather than just one session. Used when the
    UI's analysis target is a whole subject rather than a single
    session -- "select a subject entirely" shows one combined
    mean/SD across all of their recordings, same on-read (never a
    stored snapshot) approach as the per-session summary above.
    """

    vowel_trials = []
    ddk_trials = []

    for session_id in session_ids:
        vowel_trials.extend(
            r["features"] for r in get_recordings_for_session_task(session_id, "Sustained Vowel")
        )
        ddk_trials.extend(
            r["features"] for r in get_recordings_for_session_task(session_id, "DDK")
        )

    return {
        "subject_id": subject_id,
        "vowel_trials": vowel_trials,
        "vowel_mean": _compute_mean(vowel_trials),
        "vowel_sd": _compute_sd(vowel_trials),
        "ddk_trials": ddk_trials,
        "ddk_mean": _compute_mean(ddk_trials),
        "ddk_sd": _compute_sd(ddk_trials),
    }
