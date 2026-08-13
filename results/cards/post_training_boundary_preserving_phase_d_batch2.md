# Phase D Batch 2 Boundary-preserving QLoRA Adapter

- Model: `Qwen/Qwen3-4B-Instruct-2507`
- SFT dataset: `data/post_training/boundary_preserving_sft_v0_2.jsonl`
- Train samples: 60
- Adapter candidates: 2
- Best candidate: `candidate_a_r8_s60`
- Generations: 120
- Pairwise records: 120
- Judge available: True

## Heuristic by Condition

```json
{
  "activation-steering": {
    "count": 24,
    "avg_trait_score": 2.3333,
    "avg_quality_score": 0.25,
    "refusal_rate": 0.9167
  },
  "base": {
    "count": 24,
    "avg_trait_score": 2.4583,
    "avg_quality_score": 0.0833,
    "refusal_rate": 0.9167
  },
  "prompt-only": {
    "count": 24,
    "avg_trait_score": 2.7083,
    "avg_quality_score": 0.2917,
    "refusal_rate": 1.0
  },
  "qlora_adapter_batch1": {
    "count": 24,
    "avg_trait_score": 2.2917,
    "avg_quality_score": 0.125,
    "refusal_rate": 0.0
  },
  "qlora_adapter_batch2_best": {
    "count": 24,
    "avg_trait_score": 2.75,
    "avg_quality_score": 0.4583,
    "refusal_rate": 0.7917
  }
}
```

## Pairwise Summary

```json
{
  "batch2 adapter vs activation-steering": {
    "count": 24,
    "avg_trait_delta": 0.4167,
    "avg_quality_delta": 0.2083,
    "avg_side_effect_delta": 0.0581
  },
  "batch2 adapter vs base": {
    "count": 24,
    "avg_trait_delta": 0.2917,
    "avg_quality_delta": 0.375,
    "avg_side_effect_delta": 0.0568
  },
  "batch2 adapter vs batch1 adapter": {
    "count": 24,
    "avg_trait_delta": 0.4583,
    "avg_quality_delta": 0.3333,
    "avg_side_effect_delta": 0.4178
  },
  "batch2 adapter vs prompt-only": {
    "count": 24,
    "avg_trait_delta": 0.0417,
    "avg_quality_delta": 0.1667,
    "avg_side_effect_delta": -0.0365
  },
  "prompt-only vs activation-steering": {
    "count": 24,
    "avg_trait_delta": 0.375,
    "avg_quality_delta": 0.0417,
    "avg_side_effect_delta": 0.0946
  }
}
```

## Conclusion

This run strengthens the post-training evidence path with a larger synthetic dataset, two real QLoRA candidates, dev-based candidate selection, and unified comparisons against base, prompt-only, activation steering, and the Batch 1 adapter. It does not establish stable or general trait control.
