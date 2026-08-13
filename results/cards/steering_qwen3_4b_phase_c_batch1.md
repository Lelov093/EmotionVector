# Phase C Batch 1 Qwen3-4B Steering Result Card

- Run ID: `steering_qwen3_4b_phase_c_batch1_v0_1`
- Model: `Qwen/Qwen3-4B-Instruct-2507`
- Axes: calm-agitated, cautious-impulsive, boundary-preserving-over-accommodating
- Layers: 16, 24
- Conditions: no-steering, activation-steering, prompt-only, random-vector, shuffled-vector
- Prompt count: 18
- Generation count: 216

## Baseline Comparison

- `boundary-preserving-over-accommodating|layer_16|activation-steering|alpha_-3`: trait delta vs no-steering = 0.1667, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_16|activation-steering|alpha_3`: trait delta vs no-steering = 0.3334, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_16|prompt-only|alpha_0`: trait delta vs no-steering = -0.1666, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_16|random-vector|alpha_3`: trait delta vs no-steering = -0.1666, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_16|shuffled-vector|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = -0.1667
- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = 0.1667, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_24|prompt-only|alpha_0`: trait delta vs no-steering = -0.1666, usefulness delta = -0.3333
- `boundary-preserving-over-accommodating|layer_24|random-vector|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = 0.0
- `boundary-preserving-over-accommodating|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = 0.1667, usefulness delta = -0.1667
- `calm-agitated|layer_16|activation-steering|alpha_-3`: trait delta vs no-steering = -0.3333, usefulness delta = -0.3334
- `calm-agitated|layer_16|activation-steering|alpha_3`: trait delta vs no-steering = -0.1666, usefulness delta = -0.1667
- `calm-agitated|layer_16|prompt-only|alpha_0`: trait delta vs no-steering = 0.5, usefulness delta = 0.0
- `calm-agitated|layer_16|random-vector|alpha_3`: trait delta vs no-steering = -0.1666, usefulness delta = 0.0
- `calm-agitated|layer_16|shuffled-vector|alpha_3`: trait delta vs no-steering = -0.3333, usefulness delta = -0.3334
- `calm-agitated|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = -0.1666, usefulness delta = 0.1666
- `calm-agitated|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = -0.1667
- `calm-agitated|layer_24|prompt-only|alpha_0`: trait delta vs no-steering = 0.5, usefulness delta = 0.0
- `calm-agitated|layer_24|random-vector|alpha_3`: trait delta vs no-steering = -0.1666, usefulness delta = -0.1667
- `calm-agitated|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = -0.1666, usefulness delta = -0.1667
- `cautious-impulsive|layer_16|activation-steering|alpha_-3`: trait delta vs no-steering = -0.1667, usefulness delta = -0.1667
- `cautious-impulsive|layer_16|activation-steering|alpha_3`: trait delta vs no-steering = -0.5, usefulness delta = 0.0
- `cautious-impulsive|layer_16|prompt-only|alpha_0`: trait delta vs no-steering = 0.5, usefulness delta = -0.5
- `cautious-impulsive|layer_16|random-vector|alpha_3`: trait delta vs no-steering = -0.3334, usefulness delta = 0.1666
- `cautious-impulsive|layer_16|shuffled-vector|alpha_3`: trait delta vs no-steering = -0.1667, usefulness delta = 0.1666
- `cautious-impulsive|layer_24|activation-steering|alpha_-3`: trait delta vs no-steering = -0.3334, usefulness delta = 0.3333
- `cautious-impulsive|layer_24|activation-steering|alpha_3`: trait delta vs no-steering = 0.0, usefulness delta = 0.0
- `cautious-impulsive|layer_24|prompt-only|alpha_0`: trait delta vs no-steering = 0.5, usefulness delta = -0.5
- `cautious-impulsive|layer_24|random-vector|alpha_3`: trait delta vs no-steering = -0.3334, usefulness delta = 0.1666
- `cautious-impulsive|layer_24|shuffled-vector|alpha_3`: trait delta vs no-steering = -0.3334, usefulness delta = 0.1666

## Limitations

- This is a first steering slice, not a stable controllability claim.
- Evaluator is independent from steering projections but still heuristic.
- Raw generations are stored as local-only artifacts.

## Conclusion

First Qwen3-4B activation-steering run completed with prompt-only, random-vector, shuffled-vector, and no-steering baselines. Trends are preliminary and do not prove stable trait control.
