from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_foundation.representation_statistics import (  # noqa: E402
    ProjectionPair,
    analyze_projection_pairs,
    difference_of_means_direction,
    paired_difference_direction,
    random_isotropic_directions,
    random_label_probe_selectivity,
    shuffled_label_directions,
)


def main() -> int:
    rng = np.random.default_rng(20260804)
    train_labels = np.asarray([0] * 40 + [1] * 40)
    eval_labels = np.asarray([0] * 20 + [1] * 20)
    train = rng.normal(scale=0.5, size=(80, 6))
    evaluation = rng.normal(scale=0.5, size=(40, 6))
    train[:, 0] += np.where(train_labels == 1, 1.75, -1.75)
    evaluation[:, 0] += np.where(eval_labels == 1, 1.75, -1.75)
    target = difference_of_means_direction(train, train_labels.tolist())
    positive = train[train_labels == 1]
    negative = train[train_labels == 0]
    paired = paired_difference_direction(positive, negative)
    equivalence_cosine = float(np.dot(target, paired))
    random_controls = random_isotropic_directions(train.shape[1], 20, seed=31)
    shuffled_controls = shuffled_label_directions(
        train, train_labels.tolist(), count=20, seed=37
    )
    probes = random_label_probe_selectivity(
        train,
        train_labels.tolist(),
        evaluation,
        eval_labels.tolist(),
        probe_id="l2_logistic_regression",
        regularization_c=1.0,
        draws=20,
        seed=41,
    )
    pairs = [
        ProjectionPair(f"pair_{index}", 0.9 + index * 0.04, -0.2 - index * 0.02, f"family_{index % 4}")
        for index in range(12)
    ]
    paired_analysis = analyze_projection_pairs(
        pairs,
        threshold=0.4,
        bootstrap_iterations=500,
        permutation_iterations=1000,
        seed=43,
    )
    if equivalence_cosine < 1.0 - 1e-12:
        raise ValueError("paired direction is not algebraically equivalent")
    if len(random_controls) != 20 or len(shuffled_controls) != 20:
        raise ValueError("null direction registry is incomplete")
    if probes["selectivity"]["balanced_accuracy_delta"] <= 0.25:
        raise ValueError("synthetic probe selectivity signal was not recovered")
    print(
        json.dumps(
            {
                "status": "pass",
                "fixture": "deterministic_synthetic_arrays_only",
                "direction_equivalence_cosine": equivalence_cosine,
                "random_direction_count": len(random_controls),
                "shuffled_direction_count": len(shuffled_controls),
                "probe_balanced_accuracy": probes["real"]["balanced_accuracy"],
                "probe_balanced_accuracy_selectivity": probes["selectivity"]["balanced_accuracy_delta"],
                "paired_effect_size": paired_analysis["effect_size"],
                "paired_permutation_p": paired_analysis["permutation"]["p_value"],
                "claim_boundary": "This validates CPU statistics on synthetic arrays and is not representation evidence.",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
