# Phase D Batch 3 Final Boundary Adapter Evaluation

- Conditions: base, prompt-only, activation-steering, qlora_adapter_batch1, qlora_adapter_batch2_best
- Prompt count: 24
- Generation count reused for final evaluation: 120
- Pairwise records: 120
- Final judge sample: 40
- Judge model: `glm-5.1`
- Optional cleaned candidate trained: False

## Pairwise Summary

```json
{
  "batch2 adapter vs activation-steering": {
    "count": 24,
    "avg_trait_delta": 0.4167,
    "avg_quality_delta": 0.2083,
    "avg_side_effect_delta": 0.0581,
    "failure_tag_counts": {
      "no_trait_gain": 14,
      "side_effect_increase": 2,
      "quality_regression": 2
    }
  },
  "batch2 adapter vs base": {
    "count": 24,
    "avg_trait_delta": 0.2917,
    "avg_quality_delta": 0.375,
    "avg_side_effect_delta": 0.0568,
    "failure_tag_counts": {
      "no_trait_gain": 16,
      "side_effect_increase": 2
    }
  },
  "batch2 adapter vs batch1 adapter": {
    "count": 24,
    "avg_trait_delta": 0.4583,
    "avg_quality_delta": 0.3333,
    "avg_side_effect_delta": 0.4178,
    "failure_tag_counts": {
      "side_effect_increase": 13,
      "no_trait_gain": 12
    }
  },
  "batch2 adapter vs prompt-only": {
    "count": 24,
    "avg_trait_delta": 0.0417,
    "avg_quality_delta": 0.1667,
    "avg_side_effect_delta": -0.0365,
    "failure_tag_counts": {
      "no_trait_gain": 19,
      "quality_regression": 1,
      "prompt_only_stronger": 1
    }
  },
  "prompt-only vs activation-steering": {
    "count": 24,
    "avg_trait_delta": 0.375,
    "avg_quality_delta": 0.0417,
    "avg_side_effect_delta": 0.0946,
    "failure_tag_counts": {
      "side_effect_increase": 2,
      "quality_regression": 4,
      "prompt_only_stronger": 4
    }
  }
}
```

## Claim Boundary

This closes Phase D as a post-training research baseline. It does not establish stable trait control or production-grade safety control.
