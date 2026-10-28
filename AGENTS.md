# Repository Contract

本仓库维护一套可独立分发的天工 LCA 数据审核 Skill，并为后续平台接入提供可测试的规则资产。

## 产品目标

Skill 必须帮助审核员稳定完成以下工作：

1. 判断输入是过程数据集、模型数据集还是信息不足。
2. 基于可见证据识别阻断问题、建议修改和人工确认项。
3. 避免漏判，也避免因非必填字段为空而机械驳回。
4. 给出面向学习者、能够直接执行的修改建议。
5. 将人工纠偏沉淀为规则或回归案例。
6. 按需关联私有专家名册与平台审核员账号，基于专业证据推荐人选，交用户确认后才进入独立分配流程。

Skill 不负责代替审核员作最终签字，也不默认执行平台上的分配、提交、通过或驳回操作。

## 目录职责

| 目录 | 唯一职责 |
| --- | --- |
| `skill/tiangong-lca-audit/` | 可分发产品；只放 Agent 执行审核时需要的内容 |
| `src/tiangong_audit/` | 平台 API、标准化、规则引擎、报告渲染等工程实现 |
| `tests/` | Skill 合约、规则结构、内容卫生和回归案例 |
| `docs/` | 维护者架构、环境和平台接入说明 |
| `cases/` | 本地真实案件与纠偏记录；默认不提交 |

## Skill 内部的唯一事实来源

- `SKILL.md`：唯一执行流程和资源导航。
- `skill/tiangong-lca-audit/references/audit-policy.md`：唯一审核结论、严重程度和证据边界定义。
- `skill/tiangong-lca-audit/references/input-contract.md`：唯一输入充分性和标准化约定。
- `skill/tiangong-lca-audit/references/process-audit.md`：过程审核方法。
- `skill/tiangong-lca-audit/references/model-audit.md`：模型审核方法。
- `skill/tiangong-lca-audit/references/output-contract.md`：审核发现、结论和报告写法。
- `skill/tiangong-lca-audit/references/correction-policy.md`：纠偏如何升级为规则或评测。
- `skill/tiangong-lca-audit/references/platform-operations.md`：平台操作流程，必须与审核判断分离。
- `skill/tiangong-lca-audit/references/expert-selection.md`：专家专业推荐、证据与评测方法；不定义数据审核结论或分配授权。
- `skill/tiangong-lca-audit/rules/*.json`：唯一机器可读规则目录。
- `skill/tiangong-lca-audit/assets/`：输出模板和按需查询的分类数据；不得作为整份上下文加载。

同一规则不得同时维护在多个 Markdown、JSON 或 prompt 中。说明文字与结构化规则冲突时，以 `skill/tiangong-lca-audit/references/audit-policy.md` 和 `skill/tiangong-lca-audit/rules/*.json` 为准，并立即修正冲突。

## 内容准入

加入 Skill 的内容必须满足至少一项：

- 每次审核都需要执行。
- 某类审核需要按需读取。
- 能减少确定性错误或重复劳动。
- 是生成最终输出必须使用的模板或数据资产。

以下内容不得进入 Skill：

- 来源项目盘点、历史文件路径或实现过程。
- 原始 DOCX、XLSX、真实账号、未脱敏案件和人工签字。
- 仅供维护者阅读的架构或环境说明。
- 没有实际功能的占位脚本。
- 与现有规则重复的长篇摘要。

## 规则编写协议

每条规则必须包含：

- 稳定且语义明确的 `id`。
- 适用对象和审核维度。
- `rule_type`：`deterministic` 或 `judgment`。
- 默认 `severity`：`blocking`、`advisory`、`manual_review` 或 `input_gap`。
- 判断条件、所需证据、结论和一句话修改建议。
- 对信息不足和例外情况的处理。

只有可以从输入直接验证的内容才写成 `deterministic`。需要分类范围、工艺合理性或建模角色判断的内容必须写成 `judgment`，不得伪装成确定性规则。

## 纠偏升级协议

用户纠偏先进入案件记录；满足以下条件后才能修改通用规则：

1. 修正理由可泛化，不只适用于单个数据集。
2. 有明确证据说明旧判断为何错误、遗漏或过严。
3. 能写出适用范围和反例边界。
4. 同时新增或更新回归案例。

## 隐私与安全

- 真实案件只放 `cases/`，不得提交。
- 真实专家名册、邮箱、账号绑定及匹配试验只放被 Git 忽略的 `cases/expert-directory/`；代码、Skill 和测试只使用脱敏或虚构样例。
- 测试样例必须脱敏。
- 不在 Skill 中保存账号、token、个人联系方式或签字。
- 对平台执行写操作前必须获得用户明确确认。

## 完成标准

修改完成前必须：

1. 检查是否引入重复事实来源或无效路径。
2. 运行 `PYTHONPATH=src python -m tiangong_audit.cli check`。
3. 运行全部测试。
4. 对规则变更至少验证一个通过样本和一个不通过样本。
