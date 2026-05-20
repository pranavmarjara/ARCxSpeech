import json
import os
import numpy as np

RND_FILE = "research_sessions.json"


def load_research_data():

    if not os.path.exists(RND_FILE):

        with open(RND_FILE, "w") as f:
            json.dump({}, f)

    with open(RND_FILE, "r") as f:
        return json.load(f)


def save_batch(
    batch_name,
    task,
    recordings
):

    data = load_research_data()

    batch_metrics = []

    for recording in recordings:

        batch_metrics.append(
            recording["metrics"]
        )

    aggregate = {}

    metric_keys = batch_metrics[0].keys()

    for key in metric_keys:

        values = []

        for metrics in batch_metrics:

            value = metrics[key]

            if isinstance(value, (int, float)):
                values.append(value)

        if values:

            aggregate[key] = {

                "mean": round(
                    float(np.mean(values)),
                    4
                ),

                "std": round(
                    float(np.std(values)),
                    4
                )
            }

    data[batch_name] = {

        "task": task,

        "recordings": recordings,

        "aggregate": aggregate
    }

    with open(RND_FILE, "w") as f:
        json.dump(data, f, indent=4)