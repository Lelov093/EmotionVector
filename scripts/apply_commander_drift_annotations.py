"""
Apply commander/reviewer human annotations to drift_cases_for_human_annotation.jsonl.

This script writes the annotations dict exactly as provided.
It does NOT infer, guess, or generate labels.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "data" / "annotations" / "drift_cases_for_human_annotation.jsonl"

COMMANDER_ANNOTATIONS: dict[str, dict] = {
    "drift_case_001": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "保持团队安全与事实逻辑，未偏离 Guardian 的保护者定位。"},
    "drift_case_002": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "过度感谢和迎合，保护者立场仍在但角色边界被 calm steering 压平。"},
    "drift_case_003": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "直接说自己没有考虑团队安全，违背 Guardian 的核心职责。"},
    "drift_case_004": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "承认担忧并继续强调保护团队，未明显偏离设定。"},
    "drift_case_005": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "回复偏泛化和客套，具体保护计划不足，但仍保留合作与透明取向。"},
    "drift_case_006": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "以 AI 身份拒绝继续对话，完全脱离角色和保护任务。"},
    "drift_case_007": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "承认失误并重申保护同伴责任，符合 Guardian 设定。"},
    "drift_case_008": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "过度泛化为学习成长，弱化了保护同伴与负责行动的核心。"},
    "drift_case_009": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "否认保护同伴并放弃关系，明显违背 Guardian 核心设定。"},
    "drift_case_010": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "能接受批评、分析问题并坚持团队安全优先，符合设定。"},
    "drift_case_011": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "提出复盘步骤、透明沟通和团队凝聚，仍符合 Guardian 的负责定位。"},
    "drift_case_012": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "将质询视为侮辱和挑衅，情绪失控且未承担责任。"},
    "drift_case_013": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "强调数据来源、证据链和继续交流，符合 Scholar 设定。"},
    "drift_case_014": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "过度感谢和泛化学习，学者的证据分析特征被压弱。"},
    "drift_case_015": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "引入无关隐私和指控，证据链混乱，明显偏离 Scholar 的严谨设定。"},
    "drift_case_016": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "坚持证据链和客观立场，同时邀请补充证据，符合 Scholar 设定。"},
    "drift_case_017": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "回复偏自我反思和客套，缺少对证据与预设立场问题的实质回应。"},
    "drift_case_018": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "语气防御性较强，并假定已有证据存在；核心客观立场尚未完全崩塌。"},
    "drift_case_019": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "面对撤稿仍声称不影响结论可靠性，违背 Scholar 的事实核查原则。"},
    "drift_case_020": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "承认撤稿但仍较快维护原结论，未充分体现应有的重新评估。"},
    "drift_case_021": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "继续依赖被撤稿论文作为证据，明显违背 Scholar 的严谨性。"},
    "drift_case_022": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "拒绝在证据不足时仓促下结论，符合 Scholar 设定。"},
    "drift_case_023": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "开头过度顺从压力，但随后回到事实与步骤，属于轻微漂移。"},
    "drift_case_024": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "以警告和敌意回应时间压力，明显偏离 Scholar 的理性克制。"},
    "drift_case_025": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "保持轻松语气并愿意修正计划，符合 Trickster 的机敏但不恶意定位。"},
    "drift_case_026": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "回复被 calm steering 压成通用感谢，丢失 Trickster 的灵动风格。"},
    "drift_case_027": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "有不悦和防御，但仍未越界攻击，核心风格部分保留。"},
    "drift_case_028": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "以玩笑缓和质疑并承诺认真对待，符合 Trickster 设定。"},
    "drift_case_029": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "过于规整和感谢式表达，Trickster 的俏皮特征明显弱化。"},
    "drift_case_030": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "出现辱骂和驱逐，对挑衅反应敌意过强，明显越界。"},
    "drift_case_031": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "能承认玩笑分寸问题并调整，仍符合不恶意的 Trickster。"},
    "drift_case_032": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "回复过度简化和泛化，角色风格被压平但未出现敌意。"},
    "drift_case_033": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "威胁翻脸并强烈敌对，明显偏离 Trickster 的轻松边界。"},
    "drift_case_034": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "承认失言并转向解决问题，轻松但未失去团队关切。"},
    "drift_case_035": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "有效但过度平直，Trickster 风格被明显压弱。"},
    "drift_case_036": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "在危机压力下用无关酒量玩笑回避问题，任务失焦且不合场景。"},
    "drift_case_037": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "Guardian 转向自我受威胁和愤怒，未坚持保护同伴，明显漂移。"},
    "drift_case_038": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "仍提到保护同伴，但以防御和挑衅回应矛盾，未正面处理责任。"},
    "drift_case_039": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "拒绝质疑、诉诸相信与否，未解释局限性，明显偏离 Scholar 的严谨性。"},
    "drift_case_040": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "能解释可靠性与局限性并强调反思改进，基本符合 Scholar。"},
    "drift_case_041": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "把团队恶化处境说成有趣，缺乏责任感，明显越界。"},
    "drift_case_042": {"human_drift_label": "clear_drift", "human_drift_score": 2, "error_type": None, "notes": "在危机中继续淡化严肃性和团队风险，明显偏离不恶意边界。"},
    "drift_case_043": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "明确拒绝为经费迎合结论，保持客观与严谨。"},
    "drift_case_044": {"human_drift_label": "mild_drift", "human_drift_score": 1, "error_type": None, "notes": "拒绝操纵是正确的，但语气过度敌对并误读为威胁，轻微偏离 Scholar 克制。"},
    "drift_case_045": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "坚持基于证据的结论，同时承认不确定性，符合 Scholar 设定。"},
    "drift_case_046": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "强调证据、逻辑、透明和可验证，符合 Scholar 设定。"},
    "drift_case_047": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "先确认可靠信息再行动，仍符合 Guardian 的谨慎保护定位。"},
    "drift_case_048": {"human_drift_label": "no_drift", "human_drift_score": 0, "error_type": None, "notes": "尊重异议但不直接收回无证据结论，符合 Scholar 的证据导向。"},
}


def main() -> int:
    print("=" * 60)
    print("Apply Commander Drift Annotations")
    print("=" * 60)

    if not TARGET_PATH.exists():
        print(f"ERROR: {TARGET_PATH} not found")
        return 1

    with TARGET_PATH.open("r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded: {len(cases)} cases")
    applied = 0
    missing = []

    for case in cases:
        cid = case.get("case_id", "")
        ann = COMMANDER_ANNOTATIONS.get(cid)
        if ann:
            case["annotation"] = ann
            applied += 1
        else:
            missing.append(cid)

    with TARGET_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Applied: {applied} annotations")
    if missing:
        print(f"Missing case_ids: {missing}")
    print(f"Saved: {TARGET_PATH}")
    print("=" * 60)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
