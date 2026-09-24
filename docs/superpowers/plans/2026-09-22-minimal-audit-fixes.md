# 审核可靠性最小修复方案

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用四个局部补丁修复 2026-09-22 诊断中已复现的七项问题，优先保证正式审核结论由当前案件的有效证据支撑。

**Architecture:** 在现有契约和结论聚合入口补齐校验；保持规则目录、结论聚合政策、平台操作边界和文件格式。复用现有字段及测试夹具；全部复现使用脱敏数据或本地假 HTTP。

**Tech Stack:** Python、pytest、现有标准库 HTTP 客户端、Markdown Skill。

本文件仅为方案。执行时保留工作区已有未提交改动；改动按补丁逐项复核。依据和复现脚本见 [Darwin 诊断记录](/home/wangxuan/.codex/reports/tiangong-darwin-20260922/review.md)。

## 补丁 1：校验正式结论的证据输入

对应诊断 1、2、3，最先执行。

修改文件：

- `src/tiangong_audit/contracts/agent_review.py`：复用并提取单条复核校验；支持核对当前案件身份。
- `src/tiangong_audit/contracts/source.py`：为已有 SourceCheck 字段补充校验函数。
- `src/tiangong_audit/workflows/semantic_review.py`：只用有效记录生成发现、计算覆盖率与完整性。
- `src/tiangong_audit/cli.py`：`agent-findings validate` 与正式审核传入相同案件身份。
- 测试：`tests/test_agent_review.py`、`tests/test_contracts.py`、`tests/test_semantic_review_workflow.py`、`tests/test_cli.py`。

- [ ] 先加入失败用例：无证据 blocking、Source 只有 matched 标签、Agent review_id/dataset_id 错配，重现旧行为。
- [ ] Agent 校验分两层：文件结构/案件身份无效时隔离整个复核文件；身份有效但个别条目无效时，逐条隔离并报告 input_gap。rule_reviews 和 additional_findings 都要过滤；单条校验由契约模块统一提供，CLI 和聚合器不各写一套。有效条目及独立预检发现仍能形成阻断；additional_findings 沿用现有证据字段要求。
- [ ] 校验 `review_id`、`dataset_id` 与当前 manifest 一致；dataset_type 与当前类型一致。身份未知或不一致时说明原因，不将复核算作完整。
- [ ] 身份失配时必审覆盖归零，source_documents_read 也不再豁免全文读取要求；所有结论分支使用准入后的记录，防止被隔离的数据从其他入口再次生效。
- [ ] Source 校验沿用 `checked_source_id/source_ref_id`、`matched_excerpt/evidence` 的既有兼容关系。matched/conflict 需要有效 field、dataset_value、可解析的来源引用和非空证据；有对应 claim 时核对字段关联，未列入 claims 不自动否定已可定位、可追溯的人工核验证据。其他状态按其含义记录缺口或判断理由，不能一律要求“匹配证据”。
- [ ] 无效 Source 记录不参与核心字段覆盖和一致性结论，并明确产生受影响字段的信息缺口。页码不是所有来源的必填项；值为 0 不得当作缺失；不以字符串完全相等冒充语义核验。
- [ ] 回归验收：正常通过样本继续通过；无效记录单独不能导致通过或不通过；有效 blocking 与无效记录并存时仍不通过；串案记录不能支持当前案件通过；无页码但来源可追溯的有效文本证据可正常使用；claims 缺省或存在人工新增字段时，有效证据仍保留。

定向验证：

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_agent_review.py tests/test_contracts.py tests/test_semantic_review_workflow.py tests/test_cli.py -q
```

## 补丁 2：让回归覆盖对应具体问题

对应诊断 4。

修改 `src/tiangong_audit/evals/harness.py`；测试在 `tests/test_evals.py` 和 `tests/test_cli.py`。

- [ ] 先加入失败用例：电池回收样本只有三个 rule_id、没有证据和建议时，不得获得六个问题全覆盖；同规则只描述一个具体问题时，不得自动覆盖其余问题。
- [ ] 将 rule_id 匹配改为候选筛选。问题点有 evidenceKeywords 时，候选还需满足已有关键词阈值；保留原来的关键词替代匹配路径。空 evidence/judgment 不算覆盖，shouldMentionSuggestion=true 时要求非空建议。
- [ ] 一个发现可覆盖多个问题，但必须分别满足各问题的内容条件；不强制拆分发现。继续将此分数解释为内容覆盖检查，不把它当作语义正确性的证明。
- [ ] 回归验收：空发现覆盖为 0；同规则不同问题可区分；完整内容仍可全覆盖；CLI 覆盖阈值可拦住漏检结果。

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_evals.py tests/test_cli.py -q
```

## 补丁 3：明确独立安装时的解析依赖

对应诊断 5。

修改 `skill/tiangong-lca-audit/SKILL.md`、`references/input-contract.md`、`references/process-audit.md`；测试在 `tests/test_skill_contract.py`。

- [ ] 增加仅复制审核 Skill 到临时安装目录的用例，检查运行资源导航不再假定完整仓库存在。
- [ ] 在输入契约集中说明解析依赖发现：优先查找已安装的 document-granular-decompose，按实际安装路径读取其合同。SKILL.md 和过程方法只导航到该段，不重复维护解析协议。
- [ ] 配套解析能力缺失时，列明缺少的工具和受影响字段，继续可完成的局部审核，并按现有政策限制完整结论。保留原始来源和待解析材料，供补齐工具后继续处理。
- [ ] 回归验收：完整仓库仍能调用配套解析；单独安装时可明确说明依赖缺口；不会因依赖缺失静默通过，也不会降为仅用 pypdf 作唯一最终证据。

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_skill_contract.py tests/test_content_hygiene.py -q
```

## 补丁 4：补齐解析客户端的两处边界

对应诊断 6、7。

修改 `skill/document-granular-decompose/scripts/mineru_client.py`；测试在 `tests/test_document_decompose.py`。

- [ ] 增加 query 枚举不兼容、新增必填表单/query 字段未提供的假服务用例；断言客户端失败且 POST 次数为 0。
- [ ] 在 inspect_schema 中复用已有解引用/枚举读取，检查所发 query 的取值及所有 required 字段。按 schema 类型处理布尔值，避免把合法的字符串传输形式误判为不兼容。
- [ ] 增加慢响应头用例，先复现等待超过轮询预算。
- [ ] 把绝对截止保护前移到 HTTP 响应头读取前，使用可关闭连接的计时保护；传入剩余时间作为 socket timeout 仍需保留，但仅缩短 socket timeout 无法解决持续缓慢响应。确保计时器结束和连接释放，不留下后台读取线程。
- [ ] 回归验收：慢响应头、响应体和 chunk trailer 都受预算限制；允许合理调度误差；超时保留原 task ID，恢复只查询原任务，不重新上传；HTTP/HTTPS 和已有正常解析用例继续通过。

```bash
uv run --extra dev pytest tests/test_document_decompose.py -q
```

## 最终验收

- [ ] 检查资源路径和唯一事实来源；已修复问题的失败与通过对照全部覆盖。
- [ ] 运行仓库结构检查及全部测试，期望全部通过。
- [ ] 逐项核对本次 diff，确认原有用户改动保留；汇报具体修复和剩余限制。

```bash
PYTHONPATH=src uv run python -m tiangong_audit.cli check
PYTHONPATH=src uv run --extra dev pytest -q
```

执行顺序为 1 → 2 → 3 → 4；补丁 1 可以独立交付，优先消除直接影响审核结论的三个缺陷。其余补丁独立验证。当前基线为结构检查通过、259 项测试通过；新增回归后以实际测试数量为准。
