# Phase C Batch 2 Quantization Micro-benchmark

- Model: `Qwen/Qwen3-4B-Instruct-2507`
- Selected runtime: `bnb_4bit`
- Boundary: Quantized runs use Phase B FP16 vectors as a transfer micro-benchmark; formal quantized-runtime evidence requires rebuilding vectors under that runtime.

## fp16_auto_offload

- Load success: True
- Generation success: True
- Hook success: True
- CPU offload detected: True
- Tokens/sec: 2.7513
- Avg seconds/generation: 14.5388
- Conclusion: fallback

## bnb_8bit

- Load success: True
- Generation success: True
- Hook success: True
- CPU offload detected: False
- Tokens/sec: 4.1809
- Avg seconds/generation: 9.5674
- Conclusion: use

## bnb_4bit

- Load success: True
- Generation success: True
- Hook success: True
- CPU offload detected: False
- Tokens/sec: 13.6914
- Avg seconds/generation: 2.9215
- Conclusion: use
