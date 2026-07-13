---
name: tiangong-lca-audit
description: "审核天工 LCA 过程或模型数据集，检查必填内容、跨窗口一致性、清单合理性和关联过程，生成教学型审核意见、通过报告草稿、记录人工纠偏。用户提到天工平台审核、过程数据通过流程、平台暂存、完整审查报告来源、漏判、误判或过严时使用。"
---

# Tiangong LCA Audit

帮助审核员形成可复核的审核判断。审核判断和平台操作必须分开；Agent 只基于可见证据给出建议，最终结论与签字由人工确认。

## 核心工作流

1. **识别任务**：判断用户要做数据审核、报告生成、平台操作还是纠偏。
2. **检查输入**：读取 `references/input-contract.md`，判断数据集类型和信息是否足以审核。
3. **读取程序预检**：若输入包含 Runtime 生成的 `precheck.json`，先读取并复核；程序预检不是最终结论。对输入/输出流元数据问题，先确认 `flow_metadata_status=resolved` 并读取关联流快照，不得把未查询、未找到、查询失败或解析失败写成提交者漏填。
4. **执行 source 语义核验**：先确认已取得可读的 PDF/全文/附录/source table；对 PDF、Office、图片或复杂表格材料，必须直接使用项目内 `skill/document-granular-decompose` 生成 image-aware 全文，并用 `source attach-extraction` 回填为该 source 的正式抽取文本，不得只依赖 `pypdf` 文本抽取。若 `sources/*/manifest.json` 存在 `related_artifact_requirements`，或主文指向 Supplementary Table、appendix、supporting information、source table、附表、附录、补充材料，必须继续获取并纳入核验，无法取得时记录受影响字段；读取 `source-checks/claims.json`、source 摘录或 PDF 页码证据；必须同时看数据集字段和 source 原文上下文，由 Agent 抽出数量、单位口径、基准流、流身份、地点/年份、边界、分配等可核查事实并判断内容是否一致，把字段级结论写入 `source-checks/checks.json`。完整读取过被截断的抽取文本后，必须在 agent-findings 的 `source_documents_read` 中记录该路径。不得用整段字段值的字符串命中或程序规则作为最终 source 结论；source 不可用不得静默视为通过。
5. **建立证据表**：按审核维度记录字段、窗口、source 页码、可见事实和缺失信息。
6. **执行审核**：
   - 过程数据集读取 `references/process-audit.md` 和 `rules/process.json`。
   - 模型数据集读取 `references/model-audit.md` 和 `rules/model.json`；关键关联过程必须复用过程审核。
   - 两类审核都读取 `references/audit-policy.md` 和 `rules/common.json`。
7. **形成发现**：每条发现必须能指回具体字段、source 页码或数据；不能验证的判断标为人工确认或信息缺口。对预检输出 `required_rule_ids` 中的每条必审判断型规则，必须在 `agent-review/agent-findings.json` 逐条写下 pass/fail/cannot_judge/not_applicable 结论（pass/fail 必须带证据和 `evidence_refs`），可先用 `agent-findings template` 生成清单，写完用 `agent-findings validate` 校验；缺失或不完整的复核会使 semantic-review 无法形成"通过"结论。若新证据直接推翻一条预检发现，使用 `precheck_resolutions` 精确记录 `rule_id`、`location`、`resolution: refuted`、原因和证据路径，不得仅在文字中忽略该发现。
8. **聚合结论**：按 `references/audit-policy.md` 的结论规则生成通过、不通过、信息不足或需人工确认。
9. **编写输出**：读取 `references/output-contract.md`；批量审核时逐条生成独立报告，修改建议应简短、具体、适合学习者执行。
10. **处理后续**：
   - 平台操作读取 `references/platform-operations.md`；审核结论为“通过”时，也只能在人工确认后只保存草稿，包括通过报告和验证审查草稿，不得默认分配、提交或改变任务状态。
   - 结论为“不通过”“信息不足”或“需人工确认”时，只能生成审核报告、平台退回意见和待执行操作清单；不得自动执行管理员驳回、退回修改、提交审核意见或任何会改变任务状态的写操作。只有用户在审核结论之后另行明确要求“执行驳回”“退回这几条”“现在在平台驳回”等同义操作时，才允许进入对应平台写入流程。
   - 用户要求“对某条数据操作通过流程”“执行通过流程”“已通过数据走流程”等平台写入动作时，先读取 `references/platform-operations.md` 的过程/模型通过流程；过程数据走 `process-pass-flow`，生命周期模型走 `model-pass-flow`。
   - 用户要求 member 账号“待审核里所有过程数据通过”“通过审核”“进行通过审核操作”时，必须按“过程数据通过流程”理解为完整审查报告来源创建和验证审查草稿暂存；不得解释为提交审核意见或调用 `app_review_submit_comment`。
   - 用户纠偏读取 `references/correction-policy.md`。

## 审核顺序

始终按以下顺序，避免被细节带偏：

1. 核心信息是否齐全。
2. 数据集对象和目标是否明确。
3. 数据集类型是否有边界和聚合层级证据支撑。
4. 方法、边界、截断、回收口径、分配、功能单位或目标量是否一致。
5. 输入/输出或模型结构是否支撑目标。
6. 跨窗口、跨过程是否存在矛盾。
7. 来源、代表性、数据质量、分类、命名和管理信息是否可信。
8. source 文档是否支持当前数据集字段、边界、年份、地区、技术路线和关键清单。
9. 非必填内容是否改变前述判断。

## 判断底线

- 不因非必填字段为空而单独判定不通过。
- 不因输入/输出流显示“未审核”而判定数据集不通过。
- 不把分类候选当作唯一正确答案；只在分类与对象存在可直接验证的不匹配时提出问题。
- 不把行业常识或推测包装成页面证据。
- 不把 source 项目背景、参数或结论直接当作当前数据集事实；必须说明 source 如何支持当前建模内容。
- 不把 source 文本中的机械字符串命中当作语义一致；表达不同但事实一致可以判定支持，表达相同但上下文不支持不得判定通过。
- 不为了凑数量拆分或制造审核意见。
- 发现已验证的阻断问题时判定不通过；只有建议修改时仍可通过。
- 核心证据缺失时输出信息不足；规则适用范围不明确时输出需人工确认。
- 不把 `Partly terminated system`、`LCI result` 等数据集类型当作普通文本字段跳过；必须查证相应边界说明。

## 资源使用

- 分类判断先读 `references/taxonomy-guide.md`，必须实际检索 `assets/taxonomies/cfia-category-taxonomy.json` 并留存候选匹配证据；禁止整份加载大型分类文件。
- 生成审核结果使用 `assets/audit-result-template.md`。
- 生成通过报告草稿使用 `assets/approval-report-template.docx`，替换规则见 `assets/approval-report-template.md`。
- 记录纠偏使用 `assets/correction-record-template.md`。

## 输出要求

输出至少包含：

- 数据集类型与输入充分性。
- 审核结论。
- 阻断问题、建议修改、人工确认项和信息缺口。
- 每条发现的位置、证据、判断、影响及一句话修改建议。
- source 核验范围；若 source 不可用、抽取失败或字段未命中，应说明它限制了哪些判断。
- 结论适用范围和仍需人工完成的事项。
- 报告末尾的 `## 平台退回意见`；按 `references/output-contract.md` 生成可直接复制到平台的连续编号文字。

不得编造审查员身份、签字、平台提交状态或未提供的数据。
