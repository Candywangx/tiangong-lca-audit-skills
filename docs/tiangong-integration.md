# Tiangong Integration

## 当前实现

平台使用 Supabase，而不是统一的 `/api/reviews` REST 接口。Runtime 中的实现位于：

- `src/tiangong_audit/integrations/tiangong_api/client.py`：认证、RPC、表读取和写保护。
- `src/tiangong_audit/integrations/tiangong_api/reviews.py`：管理员和审核员任务队列。
- `src/tiangong_audit/integrations/tiangong_api/datasets.py`：过程、模型详情和类型自动识别。

已验证的只读接口：

| 用途 | Supabase 接口 |
| --- | --- |
| 管理员任务队列 | `qry_review_get_admin_queue_items` |
| 审核员任务队列 | `qry_review_get_member_queue_items` |
| 单条审核任务 | `qry_review_get_items` |
| 过程详情 | `processes` |
| 模型详情 | `lifecyclemodels` |
| source dataset 详情 | `sources` |
| source 文件下载 | `storage/v1/object/external_docs/...` |

## TIDAS SDK 结构校验

结构/schema 级校验通过官方 TypeScript SDK 完成，不在本仓库复制 schema 规则。首次使用前在仓库根目录安装 Node 依赖：

```bash
npm install
```

校验过程数据：

```bash
uv run python -m tiangong_audit.cli validate-structure \
  --input cases/platform-dataset.json \
  --entity-type process \
  --mode strict \
  --fail-on-error \
  --output cases/structure-validation.json
```

模型数据使用 `--entity-type model`。该值会映射到 SDK 的 `lifeCycleModel` 实体类型。

命令会调用 `@tiangong-lca/tidas-sdk/core` 的 `createTidasEntity(...).validateEnhanced()`，输出 SDK 返回的 `success`、`validationIssues`、`warnings` 和必要的错误信息。加上 `--fail-on-error` 后，只要 SDK 返回 `success: false` 或错误级 `validationIssues`，命令就返回非零状态码，便于接入 CI 或审核流水线。

## 最简单的试用步骤

1. 复制 `.env.example` 为本地 `.env`，填写平台地址、公开 key、主账号
   `TIANGONG_ADMIN_*` 和副账号 `TIANGONG_MEMBER_*`。如果要使用网页里复制出来的
   临时通行证，分别填写 `TIANGONG_ADMIN_ACCESS_TOKEN` 或
   `TIANGONG_MEMBER_ACCESS_TOKEN`。
2. 保持 `TIANGONG_API_ALLOW_WRITES=false`。
3. 推荐以 `review_id` 为入口执行只读 intake。命令会自动读取任务、数据集、source
   dataset、`external_docs` 文件，生成 claims、source-checks 和 precheck，并保存到统一 case：

```bash
uv run python -m tiangong_audit.cli intake-review \
  --review-id "<review_id>" \
  --account-role admin
```

case 主目录始终是 `cases/active/<review-id>/`；不传 `--batch-id` 时 `batch_id`
只作为元数据写入 `case.json`（默认 `<yyyymmdd>-admin`）。

4. 写回平台草稿前，先由 Agent 完成 `source-checks/checks.json` 和
   `agent-review/agent-findings.json`（用 `agent-findings validate` 校验），再执行完
   整审核阶段。该命令读取 Skill references、rules、`precheck/`、Agent 规则复核、
   `source-checks/`、source 抽取文本和模型关联过程证据，生成正式 findings 与平台
   草稿输入：

```bash
uv run python -m tiangong_audit.cli semantic-review \
  --review-id "<review_id>" \
  --batch-id "<yyyymmdd>-admin"
```

输出位于当前 case 的 `reports/semantic-context.json`、`reports/semantic-review.json`、
`reports/semantic-review.md` 和 `reports/audit-result.platform.json`。该步骤不写平台。

5. 调试队列读取时，可以拉取管理员待分配任务：

```bash
uv run python -m tiangong_audit.cli fetch-tasks \
  --role admin \
  --status unassigned \
  --output cases/queues/unassigned.latest.json
```

6. 调试副账号队列仅用于核对分配或写回相关问题，不作为日常查看待审核数据入口：

```bash
uv run python -m tiangong_audit.cli fetch-tasks \
  --role member \
  --status pending \
  --output cases/queues/pending.latest.json
```

用本地 case 状态对齐管理员队列，查看哪条已审、哪条未审：

```bash
uv run python -m tiangong_audit.cli case coverage \
  --queue cases/queues/unassigned.latest.json
```

7. 从任务结果中找到 `data_id` 和 `data_version`，自动识别并拉取数据集。查看待审核数据
   统一使用管理员账号：

```bash
uv run python -m tiangong_audit.cli fetch-dataset \
  --dataset-id "<data_id>" \
  --version "<data_version>" \
  --account-role admin \
  --output cases/platform-dataset.json
```

命令中的 `--role` 表示读取哪类队列，`--account-role` 表示使用哪个登录账号。查看待审核
队列、读取单个数据集或 intake 时统一使用 `--account-role admin`。驳回建议草稿使用 `reject` 语义角色，
默认落到管理员账号；通过报告草稿使用 `pass` 语义角色，默认落到审核员账号。

## 过程数据通过流程命令

已人工确认为通过的过程数据，使用固定命令生成完整审查报告、创建本次来源数据集并暂存验证审查。默认不写平台，只在本地 `cases/` 生成 DOCX、source payload、comment payload 和摘要：

```bash
uv run python -m tiangong_audit.cli process-pass-flow \
  --review-id "<review_id>" \
  --batch-id "<batch-id>"
```

确认 payload 无误后，增加 `--execute` 才会执行真实写入：

```bash
uv run python -m tiangong_audit.cli process-pass-flow \
  --review-id "<review_id>" \
  --batch-id "<batch-id>" \
  --execute
```

该命令使用 `pass` 语义角色（默认审核员账号），只会上传 `external_docs/{uuid}.docx`、调用 `app_dataset_create`
创建 `sources`、调用 `app_review_save_comment_draft` 暂存评论，并随后读回 `comments` 和
`sources` 验收。它不会调用 `app_review_submit_comment`，不会默认分配任务，不会把 member 待审核任务移入已审核队列。dry-run、写入和失败记录会进入当前 case 的 `operations/oplog.jsonl`。

## 驳回建议草稿命令

已人工确认为不通过或需退回修改时，使用 `reject` 语义角色（默认管理员账号）保存平台评论草稿。默认 dry-run
只输出将写回的 comment payload，不写平台：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<review-id>/reports/audit-result.platform.json
```

确认 payload 无误后，加 `--execute` 保存草稿：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<review-id>/reports/audit-result.platform.json \
  --execute
```

该命令只调用 `app_review_save_comment_draft`，不调用 `app_review_submit_comment`，不执行管理员驳回。写回成功后当前 case 标记为 `draft_saved`。

## Source 文档下载

日常使用优先执行 `intake-review`。它会从过程或模型数据集中解析
`../sources/<source-id>.xml` 引用，读取平台 `sources` 表，再从 source dataset 的
`referenceToDigitalFile` 追踪到 `../external_docs/...` 并用只读 storage 下载。

调试单个数据集 JSON 时，可以直接运行：

```bash
uv run python -m tiangong_audit.cli source fetch \
  --input cases/active/<review-id>/snapshots/dataset.raw.json \
  --review-id <review-id> \
  --account-role admin
```

`source fetch` 在提供 `--account-role` 时也会追踪平台 source dataset。若 external_docs
文件可通过公开或预签名 URL 读取，也可以用 `--external-doc-base-url` 将相对 URI 转为
HTTP URL。下载结果、hash、抽取文本和失败状态都保存在当前 case 的 `sources/` 下。
PDF/Office/图片或复杂表格 source 使用项目内 `skill/document-granular-decompose`；审核 Agent 应直接调用
该 Skill，使用 `UNSTRUCTURED_API_BASE_URL` 和
`UNSTRUCTURED_AUTH_TOKEN` 访问 `/mineru_with_images?return_txt=true`，并把生成的全文保存为当前
case 的 source 证据。
若抽取文本引用 Supplementary Table、appendix、supporting information 或 source table，
`sources/*/manifest.json` 会记录 `related_artifact_requirements`；正式 source 核验前必须继续
从平台 source dataset、出版商/DOI 页面或文中 URL 获取相关补充材料，无法取得时记录受影响字段。

自动生成 claims 可单独调试：

```bash
uv run python -m tiangong_audit.cli source claims \
  --input cases/active/<review-id>/snapshots/dataset.raw.json \
  --output cases/active/<review-id>/source-checks/claims.json
```

`submit-result` 属于审核员提交动作，会调用 `app_review_submit_comment` 并可能改变任务队列状态。即使使用非交互参数，也必须同时提供：

```bash
--force --confirm-submit app_review_submit_comment
```

没有该确认短语时，命令不得创建写入客户端。

真实平台响应包含姓名、邮箱和未公开数据集信息，只能保存在 `cases/`，不得提交。

## 接入阶段

1. 离线辅助：复制或导出数据，使用 skill 生成审核意见。
2. 半自动：通过 API 拉取待审核任务，人工确认后提交。
3. 平台内嵌：在审核页增加 AI 辅助审核面板。
4. 自动编排：人工确认后，由工具调用 API 执行分配、提交、通过或驳回。

当前只读拉取框架已实现。写操作默认禁用；即使代码支持保存草稿或提交意见，也必须在
人工确认后临时启用，不得默认执行分配、通过或驳回。

## 已知天工平台接入点

以下路径位于上游天工平台前端仓库，不属于本仓库：

- 审核管理页：`src/pages/Review`
- 管理员分配、通过、驳回：`src/services/reviews/api.ts`
- 审核员保存草稿、提交意见：`src/services/comments/api.ts`
- 过程必填字段：`src/pages/Processes/requiredFields.ts`
- 模型必填字段：`src/pages/LifeCycleModels/requiredFields.ts`
