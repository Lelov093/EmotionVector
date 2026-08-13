# Phase C Batch 3 Judge Calibration Report

- Judge model requested: `qwen3.6-plus-2026-04-02`
- Judge model effective: `glm-5.1`
- Fallback-used count: 60
- Sample count: 60
- Result count: 60
- Agreement rate: 0.4333

## Agreement By Axis

- `boundary-preserving-over-accommodating`: 0.35
- `calm-agitated`: 0.4
- `cautious-impulsive`: 0.55

## Agreement By Comparison

- `activation vs no-steering`: agreement 0.4667, judge preferences {'A': 4, 'tie': 6, 'B': 5}
- `activation vs prompt-only`: agreement 0.2667, judge preferences {'A': 7, 'B': 8}
- `activation vs random-vector`: agreement 0.5333, judge preferences {'B': 6, 'tie': 8, 'A': 1}
- `activation vs shuffled-vector`: agreement 0.4667, judge preferences {'B': 4, 'tie': 7, 'A': 4}

## Limitations

- External LLM judge is calibration evidence, not final truth.
- Disagreement with the heuristic evaluator should be treated as a research finding.
- This does not prove stable personality or behavior control.
