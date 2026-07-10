# Tiangong LCA Audit Skill

面向天工平台过程与模型数据集审核的自有 Skill。它把审核经验组织为一条可复核的决策链：

```text
输入充分性 → 证据 → 规则 → 发现 → 严重程度 → 结论 → 平台动作 → 纠偏
```

## 仓库分层

```text
skill/      可独立分发的审核能力
src/        平台 API、规则引擎和报告服务
tests/      Skill 合约、规则结构和回归案例
docs/       维护者文档
cases/      本地真实案件，默认不提交
```

`skill/tiangong-lca-audit/` 只保留审核运行时真正需要的内容：

- `SKILL.md`：唯一操作规程。
- `references/`：按任务读取的审核方法和政策。
- `rules/`：唯一机器可读规则源。
- `assets/`：审核输出模板与按需检索的分类数据。

历史审核意见只保留在 `tests/evals/` 用于回归，不作为运行时规则直接加载。

## 人工审核使用流程

第一次接触本项目？先看 10 分钟版 [docs/quickstart.md](docs/quickstart.md)。

### 1. 首次准备

复制 `.env.example` 为本地 `.env`，只在 `.env` 里填写真实配置；不要把 token 写进
`.env.example`。

命令默认使用 `uv run`，这样会按 `pyproject.toml` 自动准备 `requests`、`pypdf` 等依赖，
不依赖系统 Python 是否已安装项目包。

```bash
uv run python -m tiangong_audit.cli check
PYTHONPATH=src uv run --extra dev pytest
npm install
```

`.env` 推荐至少配置：

```env
TIANGONG_SUPABASE_URL=https://<project>.supabase.co
TIANGONG_SUPABASE_ANON_KEY=<anon-key>
TIANGONG_MEMBER_EMAIL=<reviewer-email>
TIANGONG_MEMBER_PASSWORD=<reviewer-password>
TIANGONG_ADMIN_EMAIL=<admin-email>
TIANGONG_ADMIN_PASSWORD=<admin-password>
TIANGONG_API_ALLOW_WRITES=false
# Required by skill/document-granular-decompose when using image-aware source parsing.
UNSTRUCTURED_API_BASE_URL=https://<unstructured-host>:7770
UNSTRUCTURED_AUTH_TOKEN=<mineru-api-token>
```

`TIANGONG_*_ACCESS_TOKEN` 可以留空。命令会在需要时自动登录；token 过期后也会自动刷新
并重试，包括 `external_docs` 下载。

账号角色约定：

```text
admin   查看待审核数据、读取管理员队列和日常 intake
member  审核员账号；只在写回/提交相关动作需要审核员身份时使用
reject  驳回/退回草稿语义角色，默认使用 admin 账号凭据，只保存草稿，不提交
pass    通过报告草稿语义角色，默认使用 member 账号凭据，只保存草稿，不提交
```

管理员和审核员账号由平台分配，只写入本地 `.env`（`TIANGONG_ADMIN_*` /
`TIANGONG_MEMBER_*`），不要把真实账号写进文档或示例配置。程序仍保留 `reject` / `pass`
两个操作角色，便于命令表达意图，但默认不会要求额外配置两套账号。

### 2. 找到要审核的 review_id

如果已经从页面或任务列表里知道 `review_id`，直接进入下一步。

如果需要从平台拉任务队列：

```bash
# 管理员入口查看待审核数据
uv run python -m tiangong_audit.cli fetch-tasks \
  --role admin \
  --status unassigned \
  --output cases/queues/unassigned.latest.json

# 如需区分已分配/未分配，仍从管理员队列分别拉取
uv run python -m tiangong_audit.cli fetch-tasks \
  --role admin \
  --status assigned \
  --output cases/queues/assigned.latest.json
```

从输出 JSON 中找到要处理任务的 `id` / `review_id`。

### 3. 一条命令拉取审核证据

日常审核优先使用 `intake-review`。它只读平台数据，不会提交、通过或驳回任务。

```bash
uv run python -m tiangong_audit.cli intake-review \
  --review-id "<review_id>" \
  --account-role admin
```

不传 `--batch-id` 时，`batch_id` 会作为元数据写入 `case.json`，但主目录始终使用平台
审核任务 ID：`cases/active/<review-id>/`。不要再把日期、账号或临时试跑名放进主路径。

它会自动完成：

```text
读取 review 任务
下载过程或模型 JSON
保存原始数据和标准化数据
追踪 source dataset 到 external_docs
下载 source PDF/文本，并做基础文本抽取（pypdf/文本/JSON）
标记主文引用但未落盘的 Supplementary Table、appendix、附表、附录或补充材料
从数据集生成 claims
生成 agent-review/agent-findings.template.json（必审规则待复核清单）
预留 source-checks/checks.json，由 Agent 或人工完成语义核验后写入
更新 case.json 状态
```

注意：`intake-review` 是纯程序命令，不会调用 `skill/document-granular-decompose`。
对 PDF/Office/图片或复杂表格 source，必须由 Agent 直接使用该 Skill 生成 image-aware
全文，再用 `source attach-extraction` 回填为当前 case 的正式抽取文本（见下一步）。

产物会落在：

```text
cases/active/<review-id>/
  case.json
  snapshots/
    review-task.json
    dataset.raw.json
    dataset.normalized.json
  sources/
    source-001/
      source-dataset.json
      manifest.json
      extracted.md
  source-checks/
    claims.json
    checks.json
  precheck/
    precheck.json
    precheck.md
```

### 4. 查看审核状态和证据

```bash
uv run python -m tiangong_audit.cli case status "<review_id>"
uv run python -m tiangong_audit.cli case list --status intake_completed
uv run python -m tiangong_audit.cli case coverage \
  --queue cases/queues/unassigned.latest.json
```

`case coverage` 会把平台队列和本地 `cases/index.jsonl` 对齐，输出每条任务的状态：
`not_started` 表示本地还没有 case；`intake_completed` 表示只完成拉取、source 和预检；
`draft_saved` 表示已经写过平台草稿但还没有提交最终审核。

重点看这些文件：

```text
snapshots/dataset.raw.json             被审核数据原文
snapshots/dataset.normalized.json      程序标准化后的审核输入
precheck/precheck.md                   程序确定性预检
sources/source-*/extracted.md          source PDF/文本抽取结果
sources/source-*/manifest.json         source 状态；related_artifact_requirements 记录需追踪的补充材料
source-checks/claims.json              从数据集提取的待核验字段；过程数据包含所有输入/输出交换
source-checks/checks.json              claims 和 source 文本的匹配/冲突/未命中结果
agent-review/agent-findings.json       Agent 对必审规则的逐条复核结论（正式审核输入）
```

`checks.json` 只能作为 source 证据预处理，不能直接等同最终审核结论。

### 5. 完成 Agent 规则复核与 source 语义核验

这一步是审核里真正的语义判断，由 Agent 按 Skill 完成，产物有两个：

1. `source-checks/checks.json`：Agent 读取 claims、source 原文和补充材料后写入的
   字段级核验结果（matched / conflict / ambiguous / not_found）。
2. `agent-review/agent-findings.json`：Agent 对必审判断型规则（对象一致性、边界匹配、
   清单完整性、参考流口径、来源可追溯性等）的逐条 pass/fail/cannot_judge 结论，
   每条 pass/fail 都必须带证据和 `evidence_refs`。

```bash
# 生成必审规则待复核清单（intake 已生成 agent-findings.template.json 可直接改名填写）
uv run python -m tiangong_audit.cli agent-findings template \
  --review-id "<review_id>"

# 填写后校验证据契约；不通过会逐条列出缺失
uv run python -m tiangong_audit.cli agent-findings validate \
  --review-id "<review_id>"
```

对 PDF/Office/图片或复杂表格 source，先由 Agent 直接调用
`skill/document-granular-decompose` 生成 image-aware 全文，再回填为正式抽取文本：

```bash
uv run python -m tiangong_audit.cli source attach-extraction \
  --review-id "<review_id>" \
  --source-dir source-001 \
  --extracted-text /path/to/mineru-fulltext.md
```

回填会保留旧抽取文本为 `extracted.basic.md`，更新 manifest 的
`extraction_method`，并对新全文重新扫描补充材料引用。若抽取文本超过
semantic-context 的截断上限，Agent 必须完整读取原文件，并在
`agent-findings.json` 的 `source_documents_read` 中记录该路径，否则
semantic-review 会保留"截断未确认"的人工确认项。

### 6. 执行 semantic-review

完整审核必须在写回草稿前执行 `semantic-review`。该阶段会读取 Skill references、
rules、`precheck/`、`agent-review/agent-findings.json`、`source-checks/`、source
抽取文本和模型关联过程证据，生成正式审核 findings 和平台草稿输入：

```bash
uv run python -m tiangong_audit.cli semantic-review \
  --review-id "<review_id>" \
  --batch-id "<batch-id>"
```

产物会落在：

```text
reports/semantic-context.json         semantic-review 实际读取的证据上下文
reports/semantic-review.json          结构化完整审核结果
reports/semantic-review.md            给审核员复核的证据型报告
reports/audit-result.platform.json    保存平台草稿使用的 JSON
```

`semantic-review` 只写本地报告，不写平台。只有当 Agent 规则复核通过契约校验且
source 核验结果存在时，`case.json` 才会标记 `reported=true` 并进入 `reported`
状态；输入不完整时命令仍会生成报告，但结论最高只能是"需人工确认"。

正式报告会明确给出两层结论和聚合保证：

```text
第一层 PDF/source 一致性：字段 claims 是否被 PDF/source 抽取文本支持，是否存在直接冲突。
第二层规则符合性：数据集是否符合机器规则、Agent 规则复核和审核政策。
综合结论：通过、不通过、信息不足或需人工确认；综合结论不会好于任一层结论。
存疑（ambiguous）、核心字段未证实、source 截断未确认都会阻止自动"通过"。
```

如果只是调试 Agent 审核输入，也可以额外生成任务包：

```bash
uv run python -m tiangong_audit.cli audit \
  --input cases/active/<review-id>/snapshots/dataset.raw.json \
  --output-dir cases/active/<review-id>/precheck/audit-bundle
```

### 7. 驳回建议写回为草稿

如果人工确认 `semantic-review` 的结论为“不通过”或“需退回修改”，先 dry-run 查看将写回平台的草稿 payload：

```bash
uv run python -m tiangong_audit.cli list-actions \
  --result cases/active/<review-id>/reports/audit-result.platform.json
```

输出应为 `save_comment_draft`，不是 `submit_review_comment`。

然后 dry-run 查看完整草稿内容：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<review-id>/reports/audit-result.platform.json
```

确认无误后再写回平台草稿：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<review-id>/reports/audit-result.platform.json \
  --execute
```

该命令只调用 `app_review_save_comment_draft` 保存草稿，不会调用
`app_review_submit_comment`，不会把任务提交到下一状态。dry-run、执行成功或失败都会追加到
`operations/oplog.jsonl`；执行成功后 `case.json` 会更新为 `status=draft_saved`、
`platform_written=true`。

审核结果 JSON 的最小结构如下，通常由 `semantic-review` 自动生成：

```json
{
  "review_task_id": "<review_id>",
  "dataset_id": "<dataset_id>",
  "conclusion": "rejected",
  "summary": "请按以下问题修改后重新提交。",
  "findings": []
}
```

### 8. 确认通过后生成平台草稿

只有人工确认“通过”后，才运行通过流程。默认 dry-run 只在本地生成 payload，不写平台：

```bash
uv run python -m tiangong_audit.cli process-pass-flow \
  --review-id "<review_id>" \
  --batch-id "<batch-id>"
```

确认生成的 payload 无误后，再加 `--execute`。该命令会上传 DOCX、创建 source、保存审核
草稿，但不会提交最终审核意见：

```bash
uv run python -m tiangong_audit.cli process-pass-flow \
  --review-id "<review_id>" \
  --batch-id "<batch-id>" \
  --execute
```

未传 `--output-dir` 时，产物默认落到当前 case 的
`operations/process-pass/`。真正提交审核意见的命令是 `submit-result`，必须额外提供确认短语；
日常不要误用。

### 9. 分步调试命令

下面命令主要用于排错，不是日常主流程。

```bash
# 单独拉某个数据集
uv run python -m tiangong_audit.cli fetch-dataset \
  --dataset-id "<data_id>" \
  --version "<data_version>" \
  --account-role admin \
  --output cases/debug/platform-dataset.json

# 从本地数据集 JSON 解析 source 引用
uv run python -m tiangong_audit.cli source resolve \
  --input cases/debug/platform-dataset.json \
  --output cases/debug/source-refs.json

# 从本地数据集 JSON 自动生成 claims
uv run python -m tiangong_audit.cli source claims \
  --input cases/debug/platform-dataset.json \
  --output cases/debug/claims.json

# 下载并抽取 source
uv run python -m tiangong_audit.cli source fetch \
  --input cases/debug/platform-dataset.json \
  --output-dir cases/debug/sources \
  --account-role admin

# 查看可用的历史回归案例
uv run python -m tiangong_audit.cli eval list

# 用历史审核意见给一份审核结果打分（结论一致性 + 意见点覆盖率）
uv run python -m tiangong_audit.cli eval score \
  --case-id hc-heavy-naphtha-not-approved \
  --result cases/active/<review-id>/reports/semantic-review.json \
  --require-conclusion-match \
  --fail-under 0.8

# 结构/schema 级校验
uv run python -m tiangong_audit.cli validate-structure \
  --input cases/debug/platform-dataset.json \
  --entity-type process \
  --mode strict \
  --fail-on-error \
  --output cases/debug/structure-validation.json
```

## 当前能力边界

- 可以用 Skill 对已提供的过程或模型数据进行人工辅助审核。
- 可以生成结构化审核意见、通过报告草稿和纠偏记录。
- 可以通过命令标准化过程数据，并执行第一批保守的确定性规则预检。
- 可以通过 `audit` 一次生成标准化数据、预检结果和 Agent 语义审核任务包。
- 可以通过 Supabase API 只读拉取审核任务，并自动识别和读取过程或模型数据。
- 可以通过 TIDAS TypeScript SDK 的 `validateEnhanced()` 执行结构/schema 级校验。
- 可以用统一 `case.json`、`index.jsonl` 和固定子目录追踪每条审核任务状态。
- 可以从 `review_id` 拉取平台任务和数据集，追踪 source dataset 到 `external_docs`，下载 source 文档并生成 claims；PDF/Office/图片或复杂表格 source 的高保真全文抽取由 Agent 调用项目内 `skill/document-granular-decompose` 执行，并用 `source attach-extraction` 回填到 case。
- 可以用 `agent-findings template/validate` 为每条必审判断型规则建立带证据契约的 Agent 复核记录；缺失、无效或不完整的复核会阻止结论自动"通过"。
- 可以用 `semantic-review` 物化完整审核上下文，读取 Skill references、rules、Agent 规则复核、source 抽取文本、预检和 source-checks，生成正式 findings、复核报告和平台草稿 JSON；综合结论不会好于任一层结论，复杂表格语义、工艺合理性和最终签字仍保留人工确认点。
- 可以用 `eval list/score` 把历史审核意见作为回归基线，为任意一份审核结果计算结论一致性和意见点覆盖率。
- 个案纠偏沉淀为 `skill/tiangong-lca-audit/rules/guardrails.json` 中带 `origin_case` 的数据驱动护栏，加上 `tests/evals/` 回归案例；不再把个案正则写进通用规则引擎。
- 可以用 `save-result-draft` 将驳回/退回建议保存为平台草稿，不提交，并更新 case 状态和 `operations/oplog.jsonl`。
- 可以用 `process-pass-flow` / `model-pass-flow` 对已人工确认为通过的数据生成 DOCX、创建本次 source、暂存验证审查并读回验收；只保存草稿，不提交、不分配、不改变审核结论状态。

架构和资产准入规则见 `docs/architecture.md` 与 `docs/asset-boundaries.md`。
