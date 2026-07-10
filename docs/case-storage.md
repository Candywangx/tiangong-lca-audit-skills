# Case Storage

## Representation Decision

- Entity: 审核案件归档
- Product role: 本地审核证据、报告和平台操作记录
- Primary consumers: 审核 Agent、人工复核者、回归评测维护者
- Truth status: 报告是人工复核材料；平台操作记录是审计日志
- Recommended freedom level: F2 半结构化投影
- Recommended representation: 稳定清单文件 + Markdown 报告 + 压缩原始快照

## 推荐目录

```text
cases/
  index.jsonl
  queues/
    unassigned.latest.json
    unassigned.coverage.json
    unassigned.coverage.md
    assigned.latest.json
    history/
      20260707T104314Z.unassigned.json
  active/
    <review-id>/
      case.json
      snapshots/
        review-task.json
        dataset-row.json
        dataset.raw.json
        dataset.normalized.json
        model-linked-process-refs.json
        linked-processes/
      sources/
        source-001/
          source-dataset-row.json
          source-dataset.json
          manifest.json
          original.pdf
          extracted.md
      precheck/
        precheck.json
        precheck.md
        linked-processes/
      source-checks/
        claims.json
        checks.json
      agent-review/
        agent-findings.template.json
        agent-findings.json
      reports/
        semantic-context.json
        semantic-review.json
        semantic-review.md
        audit-result.platform.json
      operations/
        oplog.jsonl
        intake-review.summary.json
        semantic-review.summary.json
  archive/
    YYYY/MM/<review-id>/
```

## 原则

- 根目录只保留 `index.jsonl`、`active/`、`archive/` 和 `queues/`，不再平铺批次文件。
- 最新队列快照统一放在 `cases/queues/<status>.latest.json`，日常查看待审核数据使用管理员队列，例如 `cases/queues/unassigned.latest.json`；需要追溯时再复制到 `cases/queues/history/<timestamp>.<status>.json`。
- 活跃案件目录固定使用 `cases/active/<review-id>/`。日期、账号、队列来源和批次号只写入 `case.json` / `index.jsonl`，不进入主路径。
- 使用审核任务 ID 作为稳定文件名，不使用 `01-dataset` 等仅在当前批次有效的序号。
- 每条任务的 `case.json` 保存当前状态、路径、步骤、批次元数据和报告位置。
- 批次根目录不保存 `intake-summary.json`、`semantic-summary.json` 这类命令副产物；需要持久化时统一放到当前任务的 `operations/<command>.summary.json`。
- `index.jsonl` 每条任务一行，支持 `rg`、脚本和后续 UI 检索；该文件是“哪条审了、哪条没审”的第一查询入口。
- 报告与证据保留可读 Markdown 和 JSON；若后续出现体积极大的原始数据集，再单独引入压缩策略并同步更新 contract。
- source 原文、下载 manifest、抽取文本和核验结果均保存在当前任务目录下，不进入 Skill。
- 平台分配、提交、通过、驳回等写操作追加到 `operations/oplog.jsonl`，不覆盖历史。
- 审核完成且平台操作结束后，将整个批次从 `active/` 移入按年月组织的 `archive/`。

## 状态字段

`case.json` 必须包含 `steps`，当前固定步骤为：

```json
{
  "fetched": false,
  "normalized": false,
  "sources_resolved": false,
  "sources_downloaded": false,
  "source_verified": false,
  "prechecked": false,
  "agent_reviewed": false,
  "semantic_reviewed": false,
  "reported": false,
  "platform_written": false
}
```

状态查询使用：

```bash
uv run python -m tiangong_audit.cli case list
uv run python -m tiangong_audit.cli case list --status reported
uv run python -m tiangong_audit.cli case status <review-id>
uv run python -m tiangong_audit.cli case coverage \
  --queue cases/queues/unassigned.latest.json
uv run python -m tiangong_audit.cli case update <review-id> \
  --status reported \
  --set-step reported \
  --report active/<review-id>/reports/audit-report.md
```

`intake-review` 会自动写入 `snapshots/`、`sources/`、`source-checks/claims.json`、
`agent-review/agent-findings.template.json` 和 `precheck/`。调试分步命令时，
`source resolve --review-id` 会标记 `sources_resolved`；`source fetch --review-id`
默认写入当前 case 的 `sources/` 并在所有 source 文件已下载或抽取后标记
`sources_downloaded`。PDF/Office/图片或复杂表格 source 应由 Agent 通过项目内
`skill/document-granular-decompose` 生成 image-aware 全文，再用
`source attach-extraction` 回填为该 source 的 `extracted.md`（旧文本保留为
`extracted.<method>.md`）。若抽取文本引用 Supplementary Table、appendix、source
table、附表、附录或补充材料，`sources/*/manifest.json` 的
`related_artifact_requirements` 会记录需继续追踪的补充材料。
`source-checks/checks.json` 由 Agent 或人工阅读 source 原文和数据集字段后写入；
写入后可用 `case update --set-step source_verified` 标记语义核验完成。
`agent-review/agent-findings.json` 保存 Agent 对必审判断型规则的逐条复核结论，
经 `agent-findings validate` 通过后 semantic-review 会标记 `agent_reviewed`。

`semantic-review` 会读取 Skill references、rules、`precheck/`、
`agent-review/agent-findings.json`、`source-checks/`、`sources/*/extracted.md`
和模型关联过程证据，写入 `reports/semantic-context.json`、
`reports/semantic-review.json`、`reports/semantic-review.md` 和
`reports/audit-result.platform.json`，并标记 `semantic_reviewed`；只有 Agent 复核
通过契约校验且 source 核验存在时才标记 `reported` 并进入 `reported` 状态。
平台草稿 dry-run、执行成功或失败都会追加到 `operations/oplog.jsonl`；写回成功后才标记
`platform_written` 并把状态更新为 `draft_saved`。

状态语义：

- `not_started`：队列中有任务，本地没有 case。
- `intake_completed`：已拉取数据、source 和预检，还没生成正式审核报告。
- `reported` / `reported_not_written`：完整审核报告已生成，平台草稿未保存。
- `draft_saved`：平台草稿已保存，但没有提交审核意见。
- `submitted` / `completed`：后续人工确认后才可标记为最终已处理。

## 建议索引字段

```json
{
  "review_id": "uuid",
  "dataset_id": "uuid",
  "version": "01.01.000",
  "dataset_type": "process",
  "name_zh": "数据集名称",
  "status": "reported",
  "conclusion": "pass",
  "platform_state": "assigned",
  "batch_id": "batch-id",
  "case_dir": "active/uuid",
  "report": "active/uuid/reports/audit-result.platform.json"
}
```

## 迁移策略

先让新批次使用该结构。旧案件保持原位并在 `index.jsonl` 中登记；确认引用和脚本均兼容后，再按批次渐进迁移，避免一次性搬动破坏历史链接。
