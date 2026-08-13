"""
Quick project health check — file system only, no torch/transformers import.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CRITICAL_FILES = [
    "README.md", "LICENSE", "DATA_LICENSES.md", "REPRODUCIBILITY.md",
    "pyproject.toml", "uv.lock", ".gitignore",
    "CITATION.cff", "CONTRIBUTING.md", "SECURITY.md",
    "configs/research/representation_atlas_v2_analysis_plan_v0_1.json",
    "configs/research/phase_3_held_out_runtime_v0_1.json",
    "configs/research/phase_3_held_out_analysis_contract_v0_1.json",
    "data/research_foundation/manifests/phase_3_family_split_v0_1.json",
    "data/research_foundation/manifests/public_dataset_use_decisions_v0_1.json",
    "research_foundation/representation_statistics.py",
    "research_foundation/atlas_v2_extraction.py",
    "research_foundation/phase3_heldout_analysis.py",
    "experiments/phase3/train_qlora.py",
    "results/summaries/atlas_v2_frozen_test_result_v0_1.json",
    "results/summaries/phase_3_held_out_results_v0_1.json",
]

GITIGNORE_PATTERNS = [
    ".venv/", "__pycache__/", "*.pyc", ".env",
    "results/logs/", "results/vectors/",
    "*.pt", "*.bin", "*.safetensors",
    "backend/", "frontend/",
    ".idea/", ".vscode/", ".agents/", "Prototypes/",
    "docs/", "report/", "results/summary/", "CHANGELOG.md",
    "main.py", "scripts/generate_summary_jsons.py",
]


def check_files() -> tuple[int, int]:
    ok, fail = 0, 0
    for rel_path in CRITICAL_FILES:
        p = PROJECT_ROOT / rel_path
        if p.exists():
            ok += 1
        else:
            print(f"  MISS: {rel_path}")
            fail += 1
    return ok, fail


def check_dirs() -> tuple[int, int]:
    required = [
        "configs/research",
        "data/research_foundation",
        "experiments/phase3",
        "research_foundation",
        "results/summaries",
        "scripts",
        "tests",
    ]
    ok, fail = 0, 0
    for d in required:
        p = PROJECT_ROOT / d
        if p.is_dir():
            ok += 1
        else:
            print(f"  MISS: {d}/")
            fail += 1
    return ok, fail


def check_gitignore() -> tuple[int, int]:
    gi_path = PROJECT_ROOT / ".gitignore"
    if not gi_path.exists():
        print("  MISS: .gitignore")
        return 0, 1
    content = gi_path.read_text(encoding="utf-8")
    ok, fail = 0, 0
    for pat in GITIGNORE_PATTERNS:
        if pat in content:
            ok += 1
        else:
            print(f"  MISS in .gitignore: {pat}")
            fail += 1
    return ok, fail


def main() -> int:
    print("=" * 60)
    print("EmotionVector Quick Project Check")
    print("=" * 60)

    # Files
    print("\n[1] Critical files:")
    f_ok, f_fail = check_files()
    print(f"  OK={f_ok} MISS={f_fail}")

    # Dirs
    print("\n[2] Required directories:")
    d_ok, d_fail = check_dirs()
    print(f"  OK={d_ok} MISS={d_fail}")

    # Gitignore
    print("\n[3] .gitignore patterns:")
    g_ok, g_fail = check_gitignore()
    print(f"  OK={g_ok} MISS={g_fail}")

    total_fail = f_fail + d_fail + g_fail
    print(f"\n{'='*60}")
    if total_fail == 0:
        print("PASS: All checks passed.")
        return 0
    else:
        print(f"WARN: {total_fail} check(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
