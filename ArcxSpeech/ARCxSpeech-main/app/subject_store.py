import json
import os
import random
import tempfile
from datetime import datetime

APP_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

SUBJECTS_FILE = os.path.join(APP_ROOT, "subjects.json")


def _atomic_write_json(filepath, data):
    """
    Writes JSON to `filepath` atomically: data is written to a temp file
    in the same directory, flushed to disk, then moved into place with
    os.replace (atomic on both POSIX and Windows). This means a crash or
    power loss mid-write can never leave `filepath` truncated or corrupt --
    either the old file is intact, or the new one is.

    Same pattern as app/assessment_store.py -- kept as its own copy here
    (rather than importing from assessment_store) so subject_store has no
    dependency on the assessment/session pipeline at all.
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


def load_subjects():
    if not os.path.exists(SUBJECTS_FILE):
        _atomic_write_json(SUBJECTS_FILE, [])

    try:
        with open(SUBJECTS_FILE, "r") as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Subject data file at {SUBJECTS_FILE} is corrupted and could "
            f"not be read ({e}). No data was modified. Restore from a "
            "backup before continuing, since this file holds every "
            "subject in the study."
        ) from e


def _generate_subject_id(existing_subjects):
    """Same RD-##### scheme the old add_patient() used in api/routes.py,
    just pulled out so it can be unit tested on its own."""
    taken = {s.get("id") for s in existing_subjects}
    while True:
        candidate = f"RD-{random.randint(10000, 99999)}"
        if candidate not in taken:
            return candidate


def add_subject(name, subject_id=None, sex="", age="", group=""):
    """Creates and persists a new subject. `subject_id` is generated
    (RD-#####) if not supplied. `group` defaults to "Unassigned" when
    left blank, matching the new UI's Add Subject modal."""

    subjects = load_subjects()

    if not subject_id:
        subject_id = _generate_subject_id(subjects)

    subject = {
        "id": subject_id,
        "name": name,
        "sex": sex,
        "age": age,
        "group": group or "Unassigned",
        "createdAt": datetime.now().isoformat(),
    }

    subjects.append(subject)
    _atomic_write_json(SUBJECTS_FILE, subjects)

    return subject


def get_subject(subject_id):
    subjects = load_subjects()
    return next((s for s in subjects if s.get("id") == subject_id), None)


def delete_subject(subject_id):
    """Removes the subject row only. Cascading delete of that subject's
    sessions/recordings/files is deliberately NOT done here -- it belongs
    in api/routes.py once session_store.py and recording_store.py exist,
    so this module stays subject-only. Returns True if a subject was
    actually removed, False if subject_id didn't exist."""

    subjects = load_subjects()
    remaining = [s for s in subjects if s.get("id") != subject_id]

    if len(remaining) == len(subjects):
        return False

    _atomic_write_json(SUBJECTS_FILE, remaining)
    return True
