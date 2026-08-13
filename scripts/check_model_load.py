import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"


def main():
    print("=" * 60)
    print("Cache Paths")
    print("=" * 60)
    print("HF_HOME:", os.environ.get("HF_HOME"))
    print("HF_HUB_CACHE:", os.environ.get("HF_HUB_CACHE"))
    print("TRANSFORMERS_CACHE:", os.environ.get("TRANSFORMERS_CACHE"))

    print("\n" + "=" * 60)
    print("Loading tokenizer")
    print("=" * 60)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    print("\n" + "=" * 60)
    print("Loading model")
    print("=" * 60)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )

    prompt = "请用一句话解释什么是 AI 角色人格稳定性。"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    print("\n" + "=" * 60)
    print("Generating")
    print("=" * 60)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=80,
            do_sample=False,
        )

    text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    print(text)


if __name__ == "__main__":
    main()