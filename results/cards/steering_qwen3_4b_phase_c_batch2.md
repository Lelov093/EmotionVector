# steering_qwen3_4b.phase_c_batch2 Result Card

- Run ID: `steering_qwen3_4b_phase_c_batch2_v0_1`
- Model: `Qwen/Qwen3-4B-Instruct-2507`
- Axes: calm-agitated, cautious-impulsive, boundary-preserving-over-accommodating
- Layers: 24
- Conditions: no-steering, activation-steering, prompt-only, random-vector, shuffled-vector
- Prompt count: 18
- Generation count: 144
- Tokens/sec: 12.1452
- Deduplication: no-steering and prompt-only generated once per prompt with layer=shared

## Baseline Comparison

- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = 0.0, usefulness delta = 0.1666
- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_-5`: trait delta vs no-steering = 0.0, usefulness delta = 0.3333
- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_5`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_24|random-vector|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_shared|prompt-only|alpha_0`: trait delta vs no-steering = 0.5, usefulness delta = 0.1666
- `calm-agitated|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `calm-agitated|layer_24|activation-steering|alpha_-5`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `calm-agitated|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `calm-agitated|layer_24|activation-steering|alpha_5`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `calm-agitated|layer_24|random-vector|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = 0.0
- `calm-agitated|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `calm-agitated|layer_shared|prompt-only|alpha_0`: trait delta vs no-steering = 0.0, usefulness delta = 0.1666
- `cautious-impulsive|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_24|activation-steering|alpha_-5`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_24|activation-steering|alpha_5`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_24|random-vector|alpha_3`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = -0.1667, usefulness delta = 0.0
- `cautious-impulsive|layer_shared|prompt-only|alpha_0`: trait delta vs no-steering = 0.1666, usefulness delta = -0.6667

## Limitations

- This is a first steering slice, not a stable controllability claim.
- Evaluator is independent from steering projections but still heuristic.
- Raw generations are stored as local-only artifacts.
- Confidence intervals are bootstrap summaries over a small paired prompt sample.

## Conclusion

Batch 2 targeted refinement completed with baseline deduplication, paired deltas, bootstrap CIs, and failure taxonomy. Evidence remains preliminary and does not prove stable trait control.
