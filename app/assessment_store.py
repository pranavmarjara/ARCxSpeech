import json
import os
import tempfile
from datetime import datetime

ASSESSMENT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "clinical_assessments.json"
)
ASSESSMENT_FILE = os.path.normpath(ASSESSMENT_FILE)


def _atomic_write_json(filepath, data):
    """
    Writes JSON to `filepath` atomically: data is written to a temp file
    in the same directory, flushed to disk, then moved into place with
    os.replace (atomic on both POSIX and Windows). This means a crash or
    power loss mid-write can never leave `filepath` truncated or corrupt --
    either the old file is intact, or the new one is.
    """

    directory = os.path.dirname(filepath) or "."

    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=".tmp_",
        suffix=".json"
    )

    try:

        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, filepath)

    except Exception:

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        raise


def load_assessments():

    if not os.path.exists(
        ASSESSMENT_FILE
    ):

        _atomic_write_json(ASSESSMENT_FILE, [])

    try:

        with open(
            ASSESSMENT_FILE,
            "r"
        ) as f:

            return json.load(f)

    except json.JSONDecodeError as e:

        raise RuntimeError(
            f"Clinical assessment data file at {ASSESSMENT_FILE} is "
            f"corrupted and could not be read ({e}). No data was "
            "modified. Restore from a backup before continuing, since "
            "this file holds all saved patient assessments."
        ) from e


def save_assessment(

    patient_name,

    patient_id,

    age,

    sex,

    vowel_trials,

    ddk_trials,

    vowel_mean,

    ddk_mean,

    ambient_mean,

    vowel_recordings,

    ddk_recordings,

    vowel_sd=None,

    ddk_sd=None,

    ambient_sd=None
):

    data = load_assessments()

    assessment = {

        "timestamp": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "patient_name": patient_name,

        "patient_id": patient_id,

        "age": age,

        "sex": sex,

        "vowel_trials": vowel_trials,

        "ddk_trials": ddk_trials,

        "vowel_mean": vowel_mean,

        "ddk_mean": ddk_mean,

        "ambient_mean": ambient_mean,

        "vowel_recordings": vowel_recordings,

        "ddk_recordings": ddk_recordings,

        "vowel_sd": vowel_sd or {},

        "ddk_sd": ddk_sd or {},

        "ambient_sd": ambient_sd or {}
    }

    data.append(
        assessment
    )

    _atomic_write_json(ASSESSMENT_FILE, data)