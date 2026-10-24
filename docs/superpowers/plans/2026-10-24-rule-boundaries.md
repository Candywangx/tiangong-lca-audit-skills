# 审核规则边界与回归实施方案

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax. User approved scope and acceptance on 2026-10-24; proceed through implementation and validation without another routine approval.

**Goal:** 完善非必填空值、来源追溯、数量单位、代表性和精确版本绑定，使真实问题可发现、合理例外不误报、证据不足不冒充错误或通过。

**Architecture:** 沿用规则 ID 与现有分层。判断条件归 rules/*.json；通用证据边界归 audit-policy；数据准入归 input-contract；程序只验证输入能直接证明的事实。上游证据和实施记录放 docs，脱敏验收放 tests，不复制上游运行时或新增在线服务。

**Tech Stack:** Python 3.11+、pytest、JSON、Markdown、独立 Agent 场景执行。

## 已批准设计

范围：五类现有规则及使其真实生效的最小标准化/预检改动。参考平台表单、数据库契约与 Portal 展示的条件，区别它们和领域审核要求。平台写入不属于本任务。

验收：至少15个独立场景（每类合法例外/真实问题或证据拒绝/证据不足），逐条检查证据、严重程度、建议和结论；每条变更规则有正反边界覆盖；判断型场景由独立 Agent 读取实际证据执行，不用预填答案冒充审核。无效/缺失证据不得产生无依据阻断，独立有效阻断不得被信息缺口覆盖。

Representation Decision：继续使用现有 F3 规则与标准化契约；事实、来源、例外保持自然语言表达。新增机器信息仅限已复现错误所必需的诊断，不把业务解释压成关键词判断。原始输入保留；有效旧格式兼容；版本/单位证据不足限制结论，不创造来源。消费者为预检、语义审核、报告和评测；验证循环为失败复现、最小修正、合法反例、独立 Agent 与全量测试。

基线：ed07322，cli check 通过，476 tests passed（20.78s）。

## Chunk 1 证据与回归

- [x] 固定并记录三个上游快照：web-portal 15d8e33a80c55c92713a7c2717928228467bab06；platform b94b89c7a4bb365186ec8a5d5909bc3183dec5d0；database 00fd4a345aa40f763b789f81b073be31ed83ffaa。
- [x] 建立 tests/fixtures/rule-boundaries/ 下独立场景、证据与单独预期；先让独立 Agent 使用旧规则执行，保存原始输出。
- [x] 审查本方案与证据边界，记录需修正处。

## Chunk 2 程序边界

文件：src/tiangong_audit/normalizer/projected.py、rule_engine/engine.py；新增 tests/test_rule_boundaries.py，必要时同步既有行为测试。

- [x] 先写失败回归并运行：原始 resultingAmount=0 不能回退到非零 meanAmount；无法解析的值不能补造数量；显式参考属性指针未匹配不能取第一条属性冒充单位；明确异 UUID/版本关联流不能用于本轮元数据证明；缺失关联元数据不等于已验证错误。
- [x] 按失败证据实现最小修正。精确数量保存的兼容性由实际消费者决定，避免在本轮扩展通用单位求解器。
- [x] 验证合法原始/投影输入、关联单位证据、现有直接冲突、错误版本及混合阻断+缺口，确认错误能检测且合法样本仍可用。
- [x] 运行定向测试，完成规格与质量复核。

## Chunk 3 规则边界

文件：skill/tiangong-lca-audit/rules/common.json、process.json；按唯一职责更新 references/audit-policy.md、input-contract.md、process-audit.md；必要时更新 model.json 的对应版本准入措辞。

- [x] 依据基线 Agent 与程序失败证据，逐条完善适用条件、证据、缺口和例外；优先既有 ID，不新增重复规则。
- [x] 非必填空值不产生发现；核心审核所需证据不可见形成缺口；来源可读/支持/冲突分别处理；合法换算和代理保留依据及用途；版本与本轮快照绑定。
- [x] 直接可验证关系保留 deterministic；需要背景/工艺/适用性解释的判断保持 judgment。
- [x] 每项更新均映射正反样本；已满足要求的部分保留并增加反例验证，不为凑数修改规则。
- [x] 独立 Agent 使用更新规则重新执行盲测；核对完整输出而非仅 rule_id。

## Chunk 4 集成与交付

- [x] 在 docs/rule-boundaries-validation.md 记录上游固定链接、旧问题、适用范围、例外、变更规则与正反样本、Agent 实际结果。
- [x] 在 tests/evals/ 或本轮独立评测资产中保留脱敏回归与预期，覆盖五类至少15场景。
- [x] 规格复核通过后执行代码质量复核；修复发现后重验。
- [x] PYTHONPATH=src python3 -m tiangong_audit.cli check
- [x] PYTHONPATH=src python3 -m pytest -q
- [x] git diff --check；确认没有重复事实源、无效路径或真实案件。
- [x] 检查原工作区仍干净且基线未移动，将经过验证的本地提交整合回原工作区并给出交付说明。

## 规格复核补充

本轮 Agent 评测明确为指定规则维度的局部审核，局部通过不等于完整审核通过，不绕过平台查重关卡。现为22项具体输入见 tests/fixtures/rule-boundaries/scenarios.json，case_id/规则/定位/预期严重程度/禁止误报/局部结论矩阵唯一维护在同目录 expected.json（执行Agent不读取）。数量0、不可解析值及显式关联身份错配另由程序回归覆盖；合法原值不因文本形式被拒。版本类的反例应拒绝旧证据，并不推定当前数据集错误。

最终交付：实现提交b69494b已整合回原工作区；整合后自检及535项测试通过。22项独立Agent场景经第二位Agent逐例语义复核接受。全部计划项完成。
