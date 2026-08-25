import json
import os
import tempfile
import uuid
from datetime import datetime

APP_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

SESSIONS_FILE = os.path.join(APP_ROOT, "sessions.json")


def _atomic_write_json(filepath, data):
    """
    Writes JSON to `filepath` atomically: data is written to a temp file
    in the same directory, flushed to disk, then moved into place with
    os.replace (atomic on both POSIX and Windows). This means a crash or
    power loss mid-write can never leave `filepath` truncated or corrupt --
    either the old file is intact, or the new one is.

    Same pattern as app/subject_store.py and app/assessment_store.py --
    kept as its own copy here (rather than importing from either) so
    session_store has no dependency on the other stores at all.
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


def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        _atomic_write_json(SESSIONS_FILE, [])

    try:
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Session data file at {SESSIONS_FILE} is corrupted and could "
            f"not be read ({e}). No data was modified. Restore from a "
            "backup before continuing, since this file holds every "
            "session in the study."
        ) from e


def get_sessions_for_subject(subject_id):
    sessions = load_sessions()
    return [s for s in sessions if s.get("subject_id") == subject_id]


def get_session(session_id):
    sessions = load_sessions()
    return next((s for s in sessions if s.get("session_id") == session_id), None)


def create_session(subject_id, name=None):
    """Creates and persists an empty session container under a subject.
    `name` auto-fills as "Session N" (N = existing session count for this
    subject + 1) when left blank, matching the new UI's Add Session
    modal. No tasks or recordings are required to create one -- those
    get added later via recording_store.py."""

    sessions = load_sessions()

    if not name:
        existing_count = len(get_sessions_for_subject(subject_id))
        name = f"Session {existing_count + 1}"

    session = {
        "session_id": str(uuid.uuid4()),
        "subject_id": subject_id,
        "name": name,
        "created_at": datetime.now().isoformat(),
    }

    sessions.append(session)
    _atomic_write_json(SESSIONS_FILE, sessions)

    return session


def delete_session(session_id):
    """Removes the session row only. Cascading delete of that session's
    recordings/files is deliberately NOT done here -- it belongs in
    api/routes.py once recording_store.py exists, same deferral pattern
    as subject_store.delete_subject. Returns True if a session was
    actually removed, False if session_id didn't exist."""

    sessions = load_sessions()
    remaining = [s for s in sessions if s.get("session_id") != session_id]

    if len(remaining) == len(sessions):
        return False

    _atomic_write_json(SESSIONS_FILE, remaining)
    return True
