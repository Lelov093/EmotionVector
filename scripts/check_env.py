import os
import sys

print("=" * 60)
print("Python")
print("=" * 60)
print("Executable:", sys.executable)
print("Version:", sys.version)

print("\n" + "=" * 60)
print("Environment Variables")
print("=" * 60)
for key in [
    "UV_INSTALL_DIR",
    "UV_CACHE_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "UV_TOOL_DIR",
    "UV_TOOL_BIN_DIR",
    "HF_HOME",
    "HF_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "HF_DATASETS_CACHE",
]:
    print(f"{key}: {os.environ.get(key)}")

print("\n" + "=" * 60)
print("PyTorch / CUDA")
print("=" * 60)
try:
    import torch

    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    print("CUDA version:", torch.version.cuda)
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("GPU count:", torch.cuda.device_count())
except Exception as e:
    print("PyTorch check failed:", repr(e))

print("\n" + "=" * 60)
print("Packages")
print("=" * 60)

packages = [
    "transformers",
    "accelerate",
    "datasets",
    "safetensors",
    "huggingface_hub",
    "nnsight",
    "fastapi",
    "uvicorn",
    "pydantic",
    "numpy",
    "pandas",
    "sklearn",
    "matplotlib",
    "tqdm",
    "rich",
]

for pkg in packages:
    try:
        __import__(pkg)
        print(f"{pkg}: OK")
    except Exception as e:
        print(f"{pkg}: FAILED - {repr(e)}")