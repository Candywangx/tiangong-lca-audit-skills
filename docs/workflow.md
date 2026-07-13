# Workflow

## 审核使用流程

1. 推荐以 `intake-review --review-id <review-id> --account-role admin` 作为平台只读取数入口；case 主目录始终是 `cases/active/<review-id>/`，不传 `--batch-id` 时 `batch_id` 只作为元数据写入 `case.json`（默认 `<yyyymmdd>-<account-role>`）。查看待审核数据统一走管理员账号，只有写回建议或通过草稿时才按 `reject` / `pass` 区分管理员和审核员语义角色。
2. `intake-review` 自动读取 `.env`，检查现有 token；若 token 失效且已配置账号密码，自动登录刷新并重试请求。
3. `intake-review` 拉取 review 任务、过程或模型数据集；过程数据先按交换 UUID/明确版本去重读取关联 `flows`，保存 `dataset.raw.json`、`flow-metadata.json`、`related-flows/` 和 `dataset.enriched.json`，再生成标准化数据与预检，更新 `case.json` 的 `fetched` 与 `normalized`。缺少版本或关联流未取得时保留状态和错误，不得猜测版本，也不得把空解析结果当作提交者漏填；模型的关联过程复用同一补全流程。
4. `intake-review` 从数据集中解析 source dataset 引用，读取平台 `sources` 表，继续追踪到 `referenceToDigitalFile` / `external_docs`，下载 source 文档并抽取基础文本；PDF/Office/图片或复杂表格 source 需要由 Agent 直接调用项目内 `skill/document-granular-decompose` 生成 image-aware 全文，再用 `source attach-extraction --review-id <review-id> --source-dir source-00N --extracted-text <fulltext>` 回填为该 source 的正式抽取文本；若抽取文本引用 Supplementary Table、appendix、supporting information、source table、附表、附录或补充材料，则在 `sources/*/manifest.json` 写入 `related_artifact_requirements`，后续审核必须继续追踪或记录不可取得的具体影响字段。
5. `intake-review` 从数据集自动生成待核验字段 claims，写入 `source-checks/claims.json`，并生成 `agent-review/agent-findings.template.json` 必审规则待复核清单；它不对 source 文本作最终一致性判断。
6. 平台最新队列快照统一保存到 `cases/queues/<status>.latest.json`；用 `case coverage --queue <queue-json>` 对齐队列和本地 case，判断哪条已审、哪条未审。需要留历史时复制到 `cases/queues/history/<timestamp>.<status>.json`。
7. 调试时仍可分别运行 `case create`、`fetch-dataset`、`source resolve`、`source fetch` 和 `source claims`。
8. Agent 按 Skill 完成两类语义判断并落盘：字段级 source 核验写入 `source-checks/checks.json`；必审判断型规则的逐条 pass/fail/cannot_judge 结论写入 `agent-review/agent-findings.json`（可先用 `agent-findings template` 生成，写完用 `agent-findings validate` 校验证据契约）。新证据推翻确定性预检时，使用 `precheck_resolutions` 精确反驳并保留证据路径。读过被截断的抽取文本后，必须在 `source_documents_read` 中记录路径。
9. 使用 `semantic-review --review-id <review-id> --batch-id <batch-id>` 执行完整审核阶段：读取 Skill references、rules、`precheck/`、`agent-review/agent-findings.json`、`source-checks/`、`sources/*/extracted.md` 和模型关联过程证据，生成 `reports/semantic-context.json`、正式 findings、`reports/semantic-review.md` 和 `reports/audit-result.platform.json`。综合结论不会好于任一层结论；Agent 复核缺失或不完整、source 核验缺失、存疑字段、核心字段未证实、截断未确认都会把结论封顶在"需人工确认"或"信息不足"。
10. `semantic-review` 只写本地报告；仅当 Agent 复核通过契约校验且 source 核验存在时才标记 `reported=true` 并进入 `reported` 状态。它不写平台、不提交、不通过、不驳回。
11. 过程审核按四个窗口、source 一致性和跨窗口关系执行；模型审核会解析关联过程引用、下载可读关联过程并复用过程预检证据。自动化合并程序预检、数据驱动个案护栏、Agent 规则复核和已写入的 source 语义核验结果；复杂表格上下文和工艺合理性仍需 Agent 或审核员阅读判断。
12. 人工确认 `reports/semantic-review.md` 和 `reports/audit-result.platform.json` 后，再执行平台草稿写回：驳回/退回建议使用 `reject` 语义角色（默认管理员账号）保存草稿，通过报告使用 `pass` 语义角色（默认审核员账号）保存草稿；不得默认提交审核意见、不得默认分配、通过或驳回。dry-run、写入和读回验收追加到 `operations/oplog.jsonl`；写回成功后 case 更新为 `draft_saved`；人工纠偏进入案件记录，并按门槛升级为护栏或评测。
13. `audit` 仍可用于调试标准化数据、程序预检和 Agent 审核任务包，但不再是日常写回草稿的前置主路径。

## 维护流程

1. 判断变化属于执行流程、审核方法、结构化规则、个案护栏、输出模板、平台集成还是单一案件。
2. 只修改对应的唯一事实来源。
3. 通用规则变化必须增加回归案例；确定性 Runtime 规则还必须更新 `RUNTIME_RULE_BINDINGS`。
4. 个案纠偏优先落到 `skill/tiangong-lca-audit/rules/guardrails.json`（带 `origin_case`）和 `tests/evals/` 回归案例，不新增引擎代码；可用 `eval score` 验证纠偏后的结果覆盖历史意见点。
5. source 核验流程变化必须至少覆盖下载成功、source 不可用、Agent 语义支持、直接冲突、相关但不足和未找到证据。
6. 检查通过样本不会因规则变化被过严驳回。
7. 运行 Skill 自检和全部测试。

## 案件归档

新案件按 `docs/case-storage.md` 使用 `active/<review-id>/`、`archive/`、`queues/` 和根级 `index.jsonl` 管理；旧案件渐进迁移，不一次性搬动。

## 平台化流程

平台接入按“读取 → 标准化 → 审核 → 人工确认 → 写回”演进。审核判断和平台写操作始终保持独立。
