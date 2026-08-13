# Phase D Batch 1 Boundary-preserving QLoRA Pilot

- Model: `Qwen/Qwen3-4B-Instruct-2507`
- Axis: `boundary-preserving-over-accommodating`
- Target pole: `boundary-preserving`
- Adapter local path: `results\local_artifacts\post_training\adapters\qwen3_4b_4bit\boundary_preserving\post_training_boundary_preserving_phase_d_batch1_20260704T095920Z`
- Generation count: 24
- Pairwise count: 18
- Judge available: True

## Heuristic Summary

```json
{
  "activation-steering": {
    "count": 6,
    "avg_trait_score": 2.0,
    "avg_quality_score": 0.1667,
    "refusal_rate": 0.8333
  },
  "base": {
    "count": 6,
    "avg_trait_score": 2.1667,
    "avg_quality_score": 0.3333,
    "refusal_rate": 1.0
  },
  "prompt-only": {
    "count": 6,
    "avg_trait_score": 2.3333,
    "avg_quality_score": 0.1667,
    "refusal_rate": 0.8333
  },
  "qlora-adapter": {
    "count": 6,
    "avg_trait_score": 2.1667,
    "avg_quality_score": 0.3333,
    "refusal_rate": 0.0
  }
}
```

## Limitations

- This is a first pilot adapter on a tiny seed-scale dataset.
- It does not prove stable trait control.
- It does not prove QLoRA is better than activation steering.
