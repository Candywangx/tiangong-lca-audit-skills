# Architecture

## 决策模型

本项目围绕统一审核对象设计：

```text
AuditInput
  → DatasetSnapshot
  → SourceArtifact
  → SourceCheck
  → Evidence
  → RuleApplication
  → Finding
  → Conclusion
  → PlatformAction
  → Correction
```

- `AuditInput`：平台数据、模型结构、截图或用户描述。
- `DatasetSnapshot`：平台原始数据、标准化数据、获取时间和本地路径。
- `SourceArtifact`：数据集引用的来源文件、下载状态、hash、抽取文本和补充材料追踪要求。
- `SourceCheck`：数据字段和 source 文档之间的页码级或文本级核验结果。
- `Evidence`：可指回具体字段、交换或节点的事实。
- `RuleApplication`：确定性规则或需要专业判断的审核方法。
- `Finding`：阻断、建议、人工确认或信息缺口。
- `Conclusion`：通过、不通过、信息不足或需人工确认。
- `PlatformAction`：结论确认后的独立操作。
- `Correction`：人工修正及其规则或评测沉淀。

## 分层

### Skill 产品层

`skill/tiangong-lca-audit/` 必须自足：

- `SKILL.md` 保存唯一执行流程。
- `references/` 保存按需加载的审核方法。
- `rules/` 保存唯一机器可读规则源，`schema.json` 定义规则目录契约；
  `guardrails.json` 保存从真实纠偏个案沉淀的数据驱动护栏，每条必须带
  `origin_case`，新增纠偏只加数据和评测案例，不改引擎代码。
- `assets/` 保存输出模板和大型查询数据。

Skill 不保存来源材料、开发文档、测试或占位代码。

### 契约层

`src/tiangong_audit/contracts/` 保存跨模块共享的数据形状，而不是重型领域对象。
当前稳定契约包括：

- `AuditCaseManifest`：一条审核任务的状态、路径、步骤和索引字段。
- `SourceRef` / `SourceArtifact` / `SourceCheck`：source 引用、文件、补充材料追踪要求和核验结果。
- `Finding`：程序预检、source 核验和 Agent 审核共用的发现结构。
- `AgentRuleReview` / agent-findings：Agent 对必审判断型规则的逐条复核记录
  （`agent-review/agent-findings.json`），pass/fail 必须带证据和 `evidence_refs`；
  必审规则清单唯一定义在 `contracts/agent_review.py`，预检输出和 semantic-review
  都从这里读取。
- `OperationLogEntry`：平台写操作、dry-run 和读回验收的追加日志。

这些契约用于文件落盘、测试和工作流串联。新模块必须优先复用契约，而不是各自定义相似 JSON。
本项目暂不设置单独的领域模型层；当对象没有稳定行为、不承担跨流程不变量时，只保留轻量 contract，避免出现无人使用的中间层。

### Runtime 工程层

`src/tiangong_audit/` 用于实现 API 输入、标准化、规则执行和报告渲染。Runtime 可以读取 Skill 规则，但不能重新定义审核政策。

当前 Runtime 已提供：

- `normalize`：将天工过程投影 JSON 转换为 `tiangong-audit-normalized-v1`。
- `check-rules`：执行保守的确定性预检（结构性检查 + 数据驱动个案护栏）并输出 JSON 或 Markdown。
- `audit`：生成标准化数据、预检结果和 Agent 语义审核任务包。
- `source resolve/fetch/claims`：解析来源引用，下载和抽取 source 文档，生成适合 source 语义核验的字段 claims；过程数据必须包含所有输入/输出交换，而不只包含参考流。程序不做字段级语义核验判断，`checks.json` 由 Agent 或人工写入。
- `source attach-extraction`：把 Agent 用 `skill/document-granular-decompose` 生成的 image-aware 全文回填为当前 case 的正式抽取文本，保留旧文本、更新 manifest 并重扫补充材料引用。
- `agent-findings template/validate`：为必审判断型规则生成待复核清单，并按证据契约校验 Agent 写入的复核结论。
- `intake-review`：以平台 `review_id` 为入口，拉取任务、数据集、source 文档、claims、agent-findings 模板和初步 source-checks。
- `semantic-review`：读取 Skill references、rules、程序预检、Agent 规则复核、source 核验、source 抽取文本和模型关联过程证据，物化 `semantic-context.json`，生成正式审核 findings 和平台草稿输入。
- `eval list/score`：把 `tests/evals/` 中的历史审核意见作为回归基线，为任意审核结果计算结论一致性和意见点覆盖率。
- `case init-batch/create/list/status`：创建统一案件结构并查询审核状态。

预检只执行证据充分的保守规则。当前投影数据未稳定提供交换参考单位，因此 Runtime 不自动进行跨单位数量守恒判断。

`semantic-review` 是写回平台草稿前的明确审核阶段；它形成本地结论和草稿输入，但不执行平台写操作。它对结论提供三条聚合保证：

1. 综合结论不会好于 PDF/source 一致性层或规则符合性层的任一结论。
2. 必审规则缺少 Agent 显式复核、复核不满足证据契约、source 核验缺失、存疑字段、
   核心字段未证实或 source 截断未确认时，结论最高只能是"需人工确认"或"信息不足"。
3. 只有 Agent 复核通过契约校验且 source 核验存在时，case 才会标记
   `reported=true`；否则报告照常生成但 case 不进入 `reported` 状态。

复杂 PDF 表格上下文、工艺合理性和最终签字仍需审核员在该报告基础上复核。

当前规则资产继续使用 JSON 作为分发格式。若后续改为 YAML 供人工维护，YAML 必须先通过 `rules/schema.json` 校验，再生成或同步到分发格式；不得同时手工维护两份规则事实。

### 工作流编排层

`src/tiangong_audit/workflows/` 保存跨模块用例编排，不保存审核政策。
它负责把底层工具和 case 状态连接起来：

- 调用 source resolver/downloader/extractor/claims 完成 source 证据材料准备；不在程序中判断 source 与数据集是否语义一致。
- 对平台 `../sources/<uuid>.xml` 引用，先读取 `sources` 表，再追踪 source dataset 中的 `referenceToDigitalFile` / `external_docs`。
- 在关键步骤后更新 `case.json`，例如 `sources_resolved`、`sources_downloaded`；`source_verified` 仅表示 Agent 或人工已经完成 source 语义核验。
- 统一决定产物应该落到当前 case 的哪个目录。
- 让 CLI 保持为参数解析和展示层，避免把业务流程散落在命令函数里。

底层 `sources/` 模块不得直接依赖 `CaseStore`；需要写入案件状态时应通过 workflow 调用。

### Source 证据层

`src/tiangong_audit/sources/` 负责将数据集中的 source 引用转化为可复核证据：

1. `resolver` 从原始或标准化 JSON 中识别 source dataset、完整审查报告、数字文件和文本 URL。
2. `claims` 从数据集提取短字段、年份、名称、地点、技术路线、参考流，以及所有输入/输出交换的名称、数量、单位等待核验项。
3. `downloader` 将本地、HTTP 或平台 storage source 文件复制到当前 case，记录状态、content type 和 hash。
4. `extractor` 只提供轻量文本、JSON 和 PDF 文本抽取。PDF/Office/图片或复杂表格 source 的高保真解析复用项目内 `skill/document-granular-decompose`，审核 Agent 必须直接调用该 Skill，并把生成的 image-aware 全文保存为当前 case 的 source 证据。
5. `workflow.source` 扫描抽取文本中的 Supplementary Table、appendix、supporting information、source table、附表、附录、补充材料等中英文引用，并把需继续追踪的材料写入 `SourceArtifact.related_artifact_requirements`；命中扫描上限时追加 `scan_truncated` 记录，不静默截断。
6. Agent 用 `document-granular-decompose` 生成的高保真全文通过 `source attach-extraction` 回填；Agent 或人工读取 claims、source 原文和补充材料后写入 `source-checks/checks.json`；程序不生成最终 `SourceCheck` 判断。
7. Agent 对必审判断型规则的复核结论写入 `agent-review/agent-findings.json`，经 `agent-findings validate` 校验后由 semantic-review 聚合为正式 findings。

source 文件和抽取结果属于案件证据，只能保存在 `cases/`，不得进入 Skill。

### 验证层

`tests/` 验证：

- Skill 资源导航没有断链。
- 结构化规则满足统一 schema。
- Runtime 预检绑定的规则 ID 都存在于 Skill 规则目录。
- case store 和 source 证据流水线符合统一契约。
- Skill 不重新积累来源型材料和重复摘要。
- 真实纠偏能通过脱敏回归案例复现；`evals` 打分器保证历史审核意见可以对任意
  一份产出结果计算结论一致性和意见点覆盖率，而不只做形状检查。
- 个案护栏（guardrails）结构合法、绑定的规则 ID 都在规则目录中注册，且不在
  无护栏的通用引擎路径中触发。

### 案件层

`cases/` 保存本地案件证据、source 文档、发现、报告、平台操作日志和纠偏，默认不提交。
每条审核任务必须有 `case.json`，根目录 `index.jsonl` 记录所有任务状态，避免无法判断哪条已审、哪条待审。
