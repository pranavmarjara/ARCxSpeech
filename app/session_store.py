import json
import os
from datetime import datetime

SESSION_FILE = "sessions.json"


def load_sessions():

    if not os.path.exists(SESSION_FILE):

        with open(SESSION_FILE, "w") as f:
            json.dump({}, f)

    with open(SESSION_FILE, "r") as f:
        return json.load(f)


def save_session(
    patient_name,
    age,
    sex,
    task,
    metrics
):

    data = load_sessions()

    if patient_name not in data:
        data[patient_name] = []

    session = {
        "timestamp": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "age": age,

        "sex": sex,

        "task": task,

        "metrics": metrics
    }

    data[patient_name].append(session)

    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=4)