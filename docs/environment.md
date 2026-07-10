# Environment

## 首版必需

- Python 3.11+
- Git

## 推荐

- `uv`：Python 项目管理。
- `pytest`：规则回归测试，通过 `uv run --extra dev pytest` 使用。

## 平台接入可选

- `TIANGONG_SUPABASE_URL`：天工平台使用的 Supabase 地址。
- `TIANGONG_SUPABASE_ANON_KEY`：平台公开的 publishable key。
- `TIANGONG_ADMIN_ACCESS_TOKEN`、`TIANGONG_ADMIN_EMAIL`、`TIANGONG_ADMIN_PASSWORD`：
  审核管理员账号配置，用于查看待审核数据、读取管理员队列、执行日常只读 intake，
  以及在人工确认后保存驳回/退回建议草稿。
  邮箱填写平台分配的管理员账号。`ACCESS_TOKEN` 可填写从网页复制的临时通行证。
- `TIANGONG_MEMBER_ACCESS_TOKEN`、`TIANGONG_MEMBER_EMAIL`、`TIANGONG_MEMBER_PASSWORD`：
  审核员账号配置，用于写回/提交相关动作需要审核员身份的场景，以及在人工确认后保存通过报告/验证审查草稿。
  邮箱填写平台分配的审核员账号。`ACCESS_TOKEN` 可填写从网页复制的临时通行证。
- `TIANGONG_API_ALLOW_WRITES`：默认必须为 `false`。
- `UNSTRUCTURED_API_BASE_URL`、`UNSTRUCTURED_AUTH_TOKEN`：项目内
  `skill/document-granular-decompose` 的配置，用于对 source PDF、Office、图片和复杂表格材料执行
  image-aware 全文抽取。
- `UNSTRUCTURED_PROVIDER`、`UNSTRUCTURED_MODEL`：可选的 `skill/document-granular-decompose`
  路由覆盖。
- 审核管理员和审核员账号权限。

从 `.env.example` 复制出本地 `.env` 后填写配置，客户端会自动读取当前目录中的
`.env`。账号、token、API key 和 `.env` 不得提交到仓库，也不得粘贴到聊天或案件
记录。

每个账号都支持两种认证方式并可同时配置：

```env
TIANGONG_ADMIN_ACCESS_TOKEN=<主账号网页临时通行证，可留空>
TIANGONG_ADMIN_EMAIL=<admin-email>
TIANGONG_ADMIN_PASSWORD=...
TIANGONG_MEMBER_ACCESS_TOKEN=<副账号网页临时通行证，可留空>
TIANGONG_MEMBER_EMAIL=<reviewer-email>
TIANGONG_MEMBER_PASSWORD=...
UNSTRUCTURED_API_BASE_URL=https://your-unstructured-host:7770
UNSTRUCTURED_AUTH_TOKEN=...
```

客户端会优先使用对应账号的 `ACCESS_TOKEN`。`reject` 是驳回草稿语义角色，默认使用
`admin` 账号凭据；`pass` 是通过草稿语义角色，默认使用 `member` 账号凭据。未填写令牌，或令牌失效并收到 HTTP 401 /
403 `bad_jwt` 时，如果已填写该账号的邮箱和密码，客户端会自动登录、获取新令牌并把
原请求重试一次。该逻辑同时覆盖 Supabase REST/RPC 和 `external_docs` storage 下载；
因此日常审核不需要从浏览器 DevTools 复制 `Authorization: Bearer ...`。

命令行可显式选择登录账号。账号角色含义：

| 账号角色 | 用途 |
| --- | --- |
| `admin` | 查看待审核数据、读取管理员队列和日常只读 `intake-review` |
| `member` | 审核员账号；只在写回/提交相关动作需要审核员身份时使用 |
| `reject` | 驳回/退回草稿语义角色，默认使用 `admin` 凭据，不提交 |
| `pass` | 通过报告草稿语义角色，默认使用 `member` 凭据，不提交 |

`fetch-tasks --role admin` 默认使用 `admin` 账号；`fetch-tasks --role member` 仅用于调试
审核员队列。查看待审核数据、`fetch-dataset` 和 `intake-review` 统一使用
`--account-role admin`。`save-result-draft` 会按结果结论自动选择 `reject` 或 `pass`；`process-pass-flow`
和 `model-pass-flow` 默认使用 `pass` 语义角色。

建议为程序创建权限受限的审核专用账号，不要使用个人主账号。自动登录不会自动开启
写操作，`TIANGONG_API_ALLOW_WRITES=false` 仍然生效。

推荐平台取数入口：

```bash
uv run python -m tiangong_audit.cli intake-review \
  --review-id "<review_id>" \
  --account-role admin \
  --batch-id "<batch-id>"
```

该命令只读平台数据，会拉取 review 任务和数据集，追踪 source dataset 到
`external_docs`，下载 source 文档；复杂 PDF/Office/图片材料应交给
`skill/document-granular-decompose` 抽取全文，并标记需追踪的 Supplementary Table、appendix 或 source table，
生成 `source-checks/claims.json`，并统一保存到 `cases/`。

本地完整验证命令：

```bash
PYTHONPATH=src uv run python -m tiangong_audit.cli check
PYTHONPATH=src uv run --extra dev pytest
```
