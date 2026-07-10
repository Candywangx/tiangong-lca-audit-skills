# 快速上手（10 分钟）

面向第一次接触本项目、且已拿到全部 `.env` 配置的人。

## 这个项目做什么

对天工平台的 LCA 数据集做审核，两个层面：

1. **数据和 source 原文是否一致**——要真的读文献原文（含附表/SI）判断，不是字符串匹配。
2. **数据是否符合审核规则**——要理解规则后判断，不是跑一遍正则。

程序负责拉数据、备证据、聚合结论、写平台草稿；**语义判断由 AI Agent（或你自己）完成并落盘**。所有平台写操作默认 dry-run，只保存草稿，不会提交、通过或驳回任何任务。

## 0. 一次性准备

```bash
cp .env.example .env   # 把拿到的 key/账号填进去，保持 TIANGONG_API_ALLOW_WRITES=false
npm install            # TIDAS 结构校验需要
uv run python -m tiangong_audit.cli check   # 自检，应输出 passed
```

命令都用 `uv run`，依赖会自动装好。

## 1. 找一条要审的任务

```bash
uv run python -m tiangong_audit.cli fetch-tasks \
  --role admin --status unassigned \
  --output cases/queues/unassigned.latest.json
```

从输出 JSON 里挑一条，记下它的 `id`（下文叫 `<review_id>`）。已经知道 `review_id` 就跳过这步。

## 2. 一条命令拉齐审核证据

```bash
uv run python -m tiangong_audit.cli intake-review \
  --review-id "<review_id>" --account-role admin
```

产物都在 `cases/active/<review_id>/`：

```text
snapshots/dataset.raw.json        被审数据原文
precheck/precheck.md              程序确定性预检（不是最终结论）
sources/source-*/extracted.md     source 文献抽取文本
source-checks/claims.json         待核验字段清单
agent-review/agent-findings.template.json   必审规则待复核清单
```

## 3. 完成两项语义判断（核心步骤）

最简单的做法：在本仓库启动 Claude（或其他接入了 `skill/tiangong-lca-audit` 的
Agent），直接说"审核 `<review_id>`"，它会按 SKILL.md 完成下面两件事。手工做也可以：

**a) 读原文核对** → 写 `source-checks/checks.json`

逐条对照 `claims.json` 和 `sources/*/extracted.md` 原文，每个字段给出
`matched / conflict / ambiguous / not_found`，带摘录和页码。扫描出的
PDF/复杂表格先用 `skill/document-granular-decompose` 抽全文，再回填：

```bash
uv run python -m tiangong_audit.cli source attach-extraction \
  --review-id "<review_id>" --source-dir source-001 \
  --extracted-text <全文文件>
```

**b) 理解规则后判断** → 写 `agent-review/agent-findings.json`

把 `agent-findings.template.json` 填完（或用 `agent-findings template` 重新生成）：
每条必审规则给 `pass / fail / cannot_judge`，pass/fail 必须带证据引用。写完校验：

```bash
uv run python -m tiangong_audit.cli agent-findings validate --review-id "<review_id>"
```

## 4. 生成正式审核报告

```bash
uv run python -m tiangong_audit.cli semantic-review \
  --review-id "<review_id>" --batch-id "<batch-id>"
```

看 `cases/active/<review_id>/reports/semantic-review.md`：两层结论（source 一致性 /
规则符合性）+ 综合结论。第 3 步没做完时报告也能生成，但结论最高只会是
"需人工确认"，不会自动"通过"。

## 5. 人工确认后，把建议存成平台草稿（可选）

自己读完报告、认可结论之后才做这步。两条路都**只保存草稿**：

```bash
# 结论是"不通过"：把退回意见存为平台草稿（先不加 --execute 看 dry-run）
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<review_id>/reports/audit-result.platform.json --execute

# 结论是"通过"且人工确认：生成通过报告草稿
uv run python -m tiangong_audit.cli process-pass-flow \
  --review-id "<review_id>" --batch-id "<batch-id>" --execute
```

## 常用查询

```bash
uv run python -m tiangong_audit.cli case status "<review_id>"   # 单条进度
uv run python -m tiangong_audit.cli case coverage \
  --queue cases/queues/unassigned.latest.json                    # 哪条审了哪条没审
```

## 安全底线

- `.env` 和 `cases/` 里的内容不提交、不外传。
- 一切写平台的命令默认 dry-run；真正提交审核意见的 `submit-result` 需要额外确认短语，日常不要用。

更完整的说明见 [README.md](../README.md)、[docs/workflow.md](workflow.md) 和 [docs/architecture.md](architecture.md)。
