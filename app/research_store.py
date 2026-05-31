import json
import os
import numpy as np
from statistics import mode
from statistics import StatisticsError
import math
from sklearn.decomposition import PCA

RND_FILE = "research_sessions.json"
BASELINE_FILE = "baseline.json"


def load_research_data():

    if not os.path.exists(RND_FILE):

        with open(RND_FILE, "w") as f:
            json.dump({}, f)

    with open(RND_FILE, "r") as f:
        return json.load(f)


def save_batch(
    batch_name,
    task,
    recordings,
    speaker_id,
    device,
    environment,
    distance,
    notes
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

            rounded_values = [

                round(v, 2)

                for v in values
            ]

            try:

                mode_value = mode(
                    rounded_values
                )

            except StatisticsError:

                mode_value = "N/A"

            aggregate[key] = {

                "mean": round(
                    float(np.mean(values)),
                    4
                ),

                "median": round(
                    float(np.median(values)),
                    4
                ),

                "mode": mode_value,

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


# =====================================
# SAVE BASELINE
# =====================================

def save_baseline(
    batch_name,
    aggregate
):

    baseline = {

        "batch_name": batch_name,

        "aggregate": aggregate
    }

    with open(
        BASELINE_FILE,
        "w"
    ) as f:

        json.dump(
            baseline,
            f,
            indent=4
        )        

# =====================================
# LOAD BASELINE
# =====================================

def load_baseline():

    if not os.path.exists(
        BASELINE_FILE
    ):

        return None

    with open(
        BASELINE_FILE,
        "r"
    ) as f:

        return json.load(f)        
    
# =====================================
# COMPUTE DRIFT
# =====================================

def compute_drift(
    baseline_aggregate,
    noise_aggregate
):

    drift_results = {}

    for feature in baseline_aggregate.keys():

        if feature not in noise_aggregate:
            continue

        baseline_mean = baseline_aggregate[
            feature
        ]["mean"]

        noise_mean = noise_aggregate[
            feature
        ]["mean"]

        if baseline_mean == 0:
            continue

        drift = abs(
            noise_mean - baseline_mean
        ) / abs(baseline_mean)

        drift_results[feature] = round(
            drift,
            6
        )

    return drift_results    

# =====================================
# FEATURE SURVIVABILITY RANKING
# =====================================

def rank_feature_survivability(
    baseline_aggregate,
    research_data
):

    feature_drifts = {}

    baseline_features = baseline_aggregate.keys()

    # ---------------------------------
    # COLLECT DRIFTS
    # ---------------------------------

    for feature in baseline_features:

        feature_drifts[feature] = []

        baseline_mean = baseline_aggregate[
            feature
        ]["mean"]

        if baseline_mean == 0:
            continue

        for batch_name, batch_data in research_data.items():

            aggregate = batch_data[
                "aggregate"
            ]

            if feature not in aggregate:
                continue

            noise_mean = aggregate[
                feature
            ]["mean"]

            drift = abs(
                noise_mean - baseline_mean
            ) / abs(baseline_mean)

            feature_drifts[
                feature
            ].append(drift)

    # ---------------------------------
    # COMPUTE MEAN DRIFT
    # ---------------------------------

    ranking = []

    for feature, drifts in feature_drifts.items():

        if len(drifts) == 0:
            continue

        mean_drift = float(
            np.mean(drifts)
        )

        ranking.append({

            "feature": feature,

            "mean_drift": round(
                mean_drift,
                6
            )
        })

    # ---------------------------------
    # SORT LOWEST DRIFT FIRST
    # ---------------------------------

    ranking = sorted(

        ranking,

        key=lambda x: x[
            "mean_drift"
        ]
    )

    return ranking

# =====================================
# PCA ANALYSIS
# =====================================

def perform_pca_analysis(
    research_data
):

    feature_vectors = []

    labels = []

    for batch_name, batch_data in research_data.items():

        recordings = batch_data[
            "recordings"
        ]

        for recording in recordings:

            vector = recording.get(
                "feature_vector",
                []
            )

            if len(vector) == 0:
                continue

            feature_vectors.append(
                vector
            )

            labels.append(
                batch_name
            )

    if len(feature_vectors) < 2:

        return None, None, None

    X = np.array(
        feature_vectors
    )

    pca = PCA(
        n_components=2
    )

    transformed = pca.fit_transform(X)

    explained_variance = pca.explained_variance_ratio_

    return (
        transformed,
        labels,
        explained_variance
    )