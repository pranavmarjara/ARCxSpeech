import json
import os
from datetime import datetime

ASSESSMENT_FILE = "clinical_assessments.json"


def load_assessments():

    if not os.path.exists(
        ASSESSMENT_FILE
    ):

        with open(
            ASSESSMENT_FILE,
            "w"
        ) as f:

            json.dump([], f)

    with open(
        ASSESSMENT_FILE,
        "r"
    ) as f:

        return json.load(f)


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

    with open(
        ASSESSMENT_FILE,
        "w"
    ) as f:

        json.dump(
            data,
            f,
            indent=4
        )