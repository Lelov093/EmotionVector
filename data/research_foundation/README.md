# Research Data Foundation

本目录承载 EmotionVector 阶段 1 的数据治理基础与阶段 2 的 representation-ready 数据冻结契约。公开数据原始快照位于 Git 忽略的 `data/external/`；本目录只保存可追溯 manifest、hash 和研究契约，不跟踪原始文本。

## 目录

- `schemas/`：provenance、family-isolated split、blind evaluation、artifact manifest、public mapping review v0.2、公开数据用途决定与 Representation Atlas v2 结果契约。
- `manifests/current_dataset_provenance_v0_1.json`：当前五个核心历史数据/评估文件的来源、哈希、用途和禁用边界。
- `manifests/public_dataset_candidates_v0_1.json`：公开数据候选的 pinned metadata、许可限制与假设性 Trait 映射；当前状态为已下载原始快照但尚未通过质量/映射门。
- `manifests/public_dataset_downloads_v0_1.json`：实际下载文件、来源、哈希、行数与解析检查。
- `manifests/public_dataset_use_decisions_v0_1.json`：项目所有者批准的两个 CC-BY-NC-4.0 来源的非商业科研用途、禁止用途与退出条件。
- `manifests/representation_family_split_v2_1.json`：只含 PKU 人工确认 `valid_single_axis` opposite-pole pairs 的单轴 representation-ready family split；原文不进入 tracked manifest。
- `manifests/representation_family_split_v2_1.freeze.json`：上述 manifest 与 test pair ID 集合的冻结 hash。
- `manifests/phase_3_family_candidate_manifest_v0_1.json`：阶段 3 的 180 条无原文候选清单；全部处于待人工复核、未分配 split 状态。
- `manifests/phase_3_expansion_candidate_manifest_v0_1.json`：v0.2 追加的 60 条无原文候选清单；排除阶段 2 与已确认 180 条，仍待人工审核。
- `manifests/phase_3_provisional_isolation_families_v0_1.json`：覆盖 240 条的机械 isolation component；不含原文，尚待 semantic merge 人工审核。
- `manifests/phase_3_final_isolation_families_v0_1.json`：240 条人工 semantic merge 审核的传递闭包与最终189个 isolation families；不含原文，尚未分配 split。
- `manifests/phase_3_additional_tranche_manifest_v0_1.json`：在train-family shortfall 11后授权的精确30条有界追加候选；full/isolation review均待完成。
- `manifests/public_mapping_pilot_v0_2.json`：当前正式人工审核入口；不含原文，记录只读 source family、抽样 provenance 与 machine-proposed family。
- `manifests/public_mapping_pilot_v0_1.json`：历史试点清单，仅用于追溯，不再用于正式标注。
- `family_taxonomy_v0_1.json`：source/task/scenario/template/semantic 五级 family 定义草案，尚待人工审核与样本赋值。
- `human_review/blind_evaluation_protocol_v0_2.md`：单研究者双轮、至少七天间隔的条件盲评与重测稳定性协议；v0.1 已废弃。
- `human_review/blind_review_pilot_packet_v0_2_round_1.jsonl` 与 `...round_2.jsonl`：由历史 Phase E 输出构造的双轮 12-item 条件盲化 pilot 包；没有人工标签。
- `human_review/public_mapping_review_guide_v0_2.md`：当前 mapping review 决策、axis/pole、PKU contrast 与 family 职责说明；v0.1 仅作历史追溯。
- `human_review/public_mapping_to_family_split_v2_contract.md`：accepted review 到五级 family allocation 和 split v2 的确定性转换边界。
- `human_review/phase_3_family_review_guide_v0_1.md`：阶段 3 单轴人工复核、质量门、family 赋值与资格判定说明；PKU 源标签不作为 Trait 标签。
- `human_review/phase_3_isolation_semantic_review_guide_v0_1.md`：细粒度 isolation ownership 的 confirm/merge/exclude 人工复核规则。

## 相关入口

```powershell
python scripts\audit_research_data_foundation.py
python scripts\build_blind_review_packet_v2.py
python scripts\build_public_dataset_mapping_pilot_v2.py
python scripts\validate_public_dataset_mapping_review_v2.py <empathetic-v0.2.jsonl> <pku-v0.2.jsonl>
python scripts\build_representation_family_split_v2_1.py --reviews <empathetic-v0.2.jsonl> <pku-v0.2.jsonl> --created-at <ISO-8601>
python scripts\validate_stage_2_data_analysis_freeze.py
python scripts\validate_representation_statistics_v0_1.py
python scripts\validate_atlas_v2_adapter_v0_1.py
python scripts\validate_atlas_v2_extraction_readiness_v0_1.py
python scripts\run_atlas_v2_train_dev_extraction.py --prepare-only
python scripts\analyze_atlas_v2_train_dev_candidates.py
python scripts\run_atlas_v2_control_extraction.py --prepare-only
python scripts\analyze_atlas_v2_controls_and_lock.py
python scripts\run_atlas_v2_frozen_test_extraction.py --prepare-only
python scripts\analyze_atlas_v2_frozen_test.py
python scripts\audit_phase_3_readiness.py
python scripts\build_phase_3_family_review_packet.py
python scripts\import_phase_3_confirmed_family_review.py <confirmed.jsonl> <cross-check.csv>
python scripts\audit_phase_3_family_isolation_options.py
python scripts\build_phase_3_expansion_review_packet.py
python scripts\import_phase_3_confirmed_expansion_and_isolation_reviews.py <expansion.jsonl> <isolation.jsonl>
python scripts\build_phase_3_additional_tranche.py
python scripts\import_phase_3_confirmed_additional_reviews.py <family.jsonl> <isolation.jsonl>
python scripts\build_phase_3_small_supplement.py
python scripts\import_phase_3_confirmed_small_supplement_reviews.py <family.jsonl> <isolation.jsonl>
python scripts\build_phase_3_family_split_and_freeze.py
python -m unittest discover -s tests -p "test_*.py" -v
```

## Atlas v2 activation 与 test-once 契约

- `schemas/atlas_v2_activation_artifact_v0_1.schema.json`：只记录模型 revision、层、pooling、样本行索引、数组 hash 与冻结数据/分析计划 hash；activation 数组必须留在 Git 忽略的 `results/local_artifacts/`，metadata 不保存 prompt/response 原文。
- `schemas/atlas_v2_selection_lock_v0_1.schema.json`：在 test 开启前锁定 train/dev 选择出的层、pooling、threshold、probe regularization、全部候选结果 hash 与六类必需 control。
- `schemas/atlas_v2_test_access_event_v0_1.schema.json`：记录唯一一次、不可逆的 test 开启事件，并将其绑定到 selection lock、模型 revision、representation specification 与计划中的本地 activation 路径。
- `scripts/open_atlas_v2_test_access.py`：仅在明确传入 `--confirm-single-test-opening` 时，以独占创建方式写入 Git 忽略的 access log；日志已存在即拒绝第二次开启。该命令必须在任何 test 原文访问、activation 提取或分析之前运行。

`validate_atlas_v2_adapter_v0_1.py` 仅使用临时合成数组验证契约，不加载模型、不使用 GPU，也不打开真实冻结 test。

`representation_atlas_v2_runtime_v0_1.json` 冻结 Qwen3-4B revision、train/dev-only 输入格式、层/pooling 小网格和本地 artifact 策略。`run_atlas_v2_train_dev_extraction.py` 的 `--prepare-only` 不加载 tokenizer/model；`--smoke` 与 `--full-train-dev` 必须显式提供模型运行确认参数。smoke 不写 canonical artifact，full 模式才写八组本地 NPZ/metadata。两种模型模式都不包含 test。

`analyze_atlas_v2_train_dev_candidates.py` 对八个冻结候选执行完整 train/dev CPU 统计并写 Git 忽略的详细结果，同时生成不含原文/activation 的 tracked summary。外部 controls 未齐全时，它固定返回 `blocked_pending_external_controls`，不会创建 selection lock。

control plan 明确披露其在 target train/dev 指标可见后、control 结果与 test 未打开前冻结。control extraction 只对 legacy `calm-agitated` 的 6 个 train pairs 运行模型，并将其限定为模板 confound stress-test；surface direction 只由 target-train response token count 拟合。`analyze_atlas_v2_controls_and_lock.py` 执行预先冻结的 veto，只有全部通过才写本地 selection lock。
`representation_atlas_v2_test_runtime_v0_1.json` 在唯一 test opening 前固定模型 revision、layer 24、`last_response_token`、14-response test-only 范围、输出路径与统计 seed。`run_atlas_v2_frozen_test_extraction.py` 的 prepare-only 模式不读取 test 原文；真实运行要求已经存在且完全匹配的唯一 access event，并拒绝覆盖既有 test artifact。`analyze_atlas_v2_frozen_test.py` 只从冻结 artifact 计算预定 target、null、control、probe 与 selectivity 指标，结果状态保持 exploratory。
`phase_3_limited_fair_comparison_protocol_v0_1` 将用户授权的阶段 3 限定为单轴、非确认性的公平比较，并冻结方法条件、数据门、人工评估、null controls 与声明边界。`audit_phase_3_readiness.py` 只读取现有资产并生成 tracked readiness summary；它不加载模型或使用 GPU，且在新 human-reviewed family-isolated 数据准备完成前保持执行门关闭。

`phase_3_family_data_contract_v0_1` 冻结阶段 3 候选来源、抽样、阶段 2 全 split 排除和复核后最低 family 目标。`build_phase_3_family_review_packet.py` 只做 CPU 数据处理：tracked manifest 不含 prompt/response，原文复核包写入 Git 忽略的 `results/local_artifacts/`。候选生成不会自动产生 Trait 真值、split 或执行授权。

`import_phase_3_confirmed_family_review.py` 以用户确认 JSONL 为主、CSV 为逐字段交叉核对，将审核写入新的 Git 忽略正式文件并保留原 packet。tracked acceptance 只记录 hash、计数、资格与审计状态，不包含原文。当前 180 条审核已完成，但五级 family 复用把全部记录连接成一个 component，因此 split 执行门保持关闭。

`audit_phase_3_family_isolation_options.py` 对五级冻结规则及更窄 ownership 组合做 CPU-only 结构审计。所有组合均不能满足互斥的 40/15/40 门；即使把每条 candidate 当作独立 component（仅为数学上界，不是可接受 family contract），预留 55 个 dev/test component 后也只剩 21 个 QLoRA-train component。

盲评 condition key 默认写入 gitignored 的 `results/local_artifacts/research_foundation/`，不得发给标注者。正式评估必须重新冻结样本、随机化记录与访问日志，不能把当前 pilot 直接升级为确认性测试集。

## 当前边界

- 现有 v0.1/v0.2 数据未被改写。
- `public_dataset_use_decisions_v0_1.json` 已记录非商业科研用途决定，但它不等于法律意见、商业许可、Trait 标签有效性或原始数据再分发许可。
- PKU 六个 JSONL 按 LF/CRLF 记录边界均可完整解析，共 83,415 条。上一轮“5 条坏行”是 `splitlines()` 错把 JSON 字符串内部 Unicode 分隔符当成记录边界的假阳性，已修正并保留回归测试。
- AI 预标注、heuristic 与 LLM Judge 不构成独立人工标注。
- 当前评审是单研究者双轮重测，只能衡量同一人的评分稳定性，不能声称多人一致性或独立外部验证。
- family taxonomy 已用于人工确认的 mapping review；阶段 2 当前只冻结 `boundary-preserving–over-accommodating` 的 26 个 PKU opposite-pole pairs（11/8/7），样本量不足以支持强确认性结论。
- mapping review v0.2 的 `source_family_id` 由 provenance 生成并校验；人工只审阅 task/scenario/template/semantic 四个 family。`needs_rewrite` 原文不会进入 split 导出。
- `same_axis_not_opposite` 保留为历史 mapping 状态，但不会进入 paired representation contrast。
