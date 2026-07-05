import json
import os
import numpy as np
from statistics import mode
from statistics import StatisticsError
from collections import Counter
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


def _compute_aggregate(batch_metrics):
    """
    Given a list of metrics dicts (one per recording, all for the same
    preprocessing stage), computes mean/median/mode/std per metric.
    """

    aggregate = {}

    if not batch_metrics:
        return aggregate

    metric_keys = batch_metrics[0].keys()

    for key in metric_keys:

        values = []

        for metrics in batch_metrics:

            value = metrics.get(key)

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

    return aggregate


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
    """
    recordings: list of
        {
            "filepath": str,
            "stages": {
                stage_key: {
                    "label": str,
                    "layers_applied": [...],
                    "metrics": {...}
                },
                ...
            },
            "feature_vector": [...]   (drawn from the full 2-layer stage,
                                        used by PCA exactly as before)
        }

    Computes an aggregate (mean/median/mode/std per metric) independently
    for each preprocessing stage ("No Layer" / "1 Layer" / "2 Layers"),
    stored under "aggregate_by_stage", so R&D History can show how each
    layer shifts biomarker values relative to raw audio.

    "aggregate" (top-level, flat) is kept for backward compatibility with
    Set Baseline / Compute Drift / Rank Survivability / PCA, which are
    stage-agnostic and continue to operate on the fully preprocessed
    ("2 Layers") stage, exactly as they did before staged extraction was
    added.
    """

    data = load_research_data()

    stage_keys = []

    if recordings:
        stage_keys = list(recordings[0]["stages"].keys())

    aggregate_by_stage = {}

    for stage_key in stage_keys:

        batch_metrics = [
            recording["stages"][stage_key]["metrics"]
            for recording in recordings
            if stage_key in recording["stages"]
        ]

        aggregate_by_stage[stage_key] = _compute_aggregate(batch_metrics)

    stage_labels = {}

    if recordings:
        stage_labels = {
            stage_key: recordings[0]["stages"][stage_key]["label"]
            for stage_key in stage_keys
        }

    # Backward-compatible flat aggregate: the full-preprocessing stage
    # (last stage key) if staged data exists, else empty.
    full_stage_key = stage_keys[-1] if stage_keys else None
    flat_aggregate = aggregate_by_stage.get(full_stage_key, {}) if full_stage_key else {}

    data[batch_name] = {

        "task": task,

        "speaker_id": speaker_id,

        "device": device,

        "environment": environment,

        "distance_cm": distance,

        "notes": notes,

        "recordings": recordings,

        "stage_labels": stage_labels,

        # Per-stage aggregates, keyed by stage key -- powers the R&D
        # History radio-button stage comparison.
        "aggregate_by_stage": aggregate_by_stage,

        # Flat aggregate for Set Baseline / Compute Drift / Rank
        # Survivability / PCA (stage-agnostic, uses full pipeline).
        "aggregate": flat_aggregate
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

    # Different batches can carry feature vectors of different lengths --
    # either because they mix tasks (Sustained Vowel vs DDK produce a
    # different number of features), or because they were saved under an
    # older/newer version of feature_extractor.py. PCA needs one
    # consistent length across all rows, so keep only the vectors
    # matching the most common length and drop the rest instead of
    # crashing with a ragged-array error.

    lengths = [
        len(vector)
        for vector in feature_vectors
    ]

    most_common_length = Counter(
        lengths
    ).most_common(1)[0][0]

    filtered = [
        (vector, label)
        for vector, label in zip(feature_vectors, labels)
        if len(vector) == most_common_length
    ]

    if len(filtered) < 2:

        return None, None, None

    feature_vectors, labels = zip(*filtered)

    feature_vectors = list(feature_vectors)

    labels = list(labels)

    X = np.array(
        feature_vectors
    )

    if X.shape[0] < 2 or X.shape[1] < 2:

        return None, None, None

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