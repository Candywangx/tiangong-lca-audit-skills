# 输入契约

## 1. 可接受输入

- 天工 API 原始 JSON。
- 已投影为窗口结构的 JSON。
- 模型数据与关联过程数据包。
- 页面截图或用户描述；此类输入通常只能做局部审核。
- 已有审核意见、报告草稿或人工纠偏。

完整审核还需要平台题目查重证据；执行条件和暂停边界以 `audit-policy.md` 的“审核前题目查重关卡”为准。只提供离线数据、无法验证平台搜索结果时，可整理输入，但不得跳过关卡形成完整审核结论。

## 2. 类型识别

优先使用显式类型字段。没有显式类型时：

- 包含过程信息、建模信息、管理信息和输入/输出窗口，或存在 `processId`：视为过程候选。
- 包含模型目标、模型图或关联过程列表，或存在 `modelId`：视为模型候选。
- 两者均无法确认：标记“类型未确认”，不要继续形成完整结论。

## 3. 过程审核最低输入

完整审核至少需要：

- 数据集名称或对象。
- 过程信息。
- 建模信息与数据集类型。
- 输入/输出交换。
- 版本或可识别的数据集标识。

缺少管理信息时可以先审核内容质量，但不能确认发布与可追溯性要求是否满足。

过程数据语义审核还应尽量取得以下关联证据：

- 关键输入/输出流的流类型、分类、参考单位、参考属性和中英文名称。
- raw TIDAS 输入中的交换流 UUID、版本、交换短描述、底层 flow 数据集名称、流类型、分类、参考属性和参考单位；交换短描述缺中文与底层 flow 数据集本身缺中文必须分开记录。
- 来源数据集、背景报告、完整审查报告和数据处理说明。
- source 原文、PDF 页码证据、下载或抽取状态，以及 source 中可直接支持或否定当前数据集字段的摘录。
- 当前分类路径，以及分类判断时实际检索到的候选分类。
- 关联背景过程或已终止过程说明；当数据集类型为 `Partly terminated system` 或 `LCI result` 时尤其必须取得。

缺少这些关联证据时，程序预检可以继续，但完整审核结论必须受到限制；不得因为页面主表未显示底层流属性而默认流、单位或类型正确。

## 4. 模型审核最低输入

完整审核至少需要：

- 模型名称、目标产品和功能单位或目标量。
- 模型结构或节点连接关系。
- 关联过程列表。
- 关键关联过程的可审数据。

只有模型表单、没有关联过程时，结论通常为信息不足。

## 5. 标准化摘要

开始审核前先形成：

```text
任务类型：
数据集类型：
数据集名称：
数据集 ID / 版本：
已提供内容：
缺失内容：
可完成的审核范围：
```

如果输入是部分截图或文字描述，必须明确“仅审核已提供范围”。

## 6. 自动规则执行边界

- 数量守恒或尺度比较必须具备可比较的参考单位；单位缺失时交由 Agent 或人工判断。
- 分类合理性、关键流完整性和工艺边界属于语义审核，不因程序未发现问题而视为通过。
- 数据集类型、回收建模口径、分配方法、截断和水边界属于核心语义审核；若输入缺少必要证据，输出信息不足或人工确认。
- 程序预检结论必须使用“预检”前缀，不得冒充完整审核结论。

## 7. Source 核验输入

source 核验材料可以包括：

- `source-refs.json`：从数据集解析出的 source 引用。
- `sources/*/manifest.json`：source 下载、hash、抽取状态、错误信息，以及 `related_artifact_requirements` 中列出的补充材料追踪要求。PDF/Office/图片或复杂表格 source 应使用项目内 `skill/document-granular-decompose` 默认 advanced 高保真解析，只有需独立图片描述时启用图片增强；manifest 同时保存导入证据包的解析溯源元数据。
- `sources/*/extracted.md`：正式抽取文本；解析证据应保留页码和块索引。
- `sources/*/parsing/`：导入的完整解析证据包。业务 JSON、块渲染文本、服务全文和请求/schema 记录分别保留，文件语义见 [解析合同](../../document-granular-decompose/references/request-response.md)。
- PDF/全文、补充材料、附录、source table、raw import 表或工程资料的本地路径、URL、checksum 或受控附件位置。
- `source-checks/claims.json`：程序抽取的待核验字段清单，只是 Agent source 语义核验的输入，不是核验结论；过程数据必须把所有输入/输出交换的方向、名称、数量和单位等可见字段纳入 claims，不得只抽取参考流。
- `source-checks/checks.json`：Agent 或人工阅读数据集字段与 source 原文后写出的字段级语义核验状态；不得由字符串匹配程序自动生成最终结论。

取得解析包后，用 `source attach-extraction --review-id <review-id> --source-dir source-00N --extracted-text <DIR/extracted.md> --extraction-dir <DIR>` 回填。
`--extracted-text` 指向带页/块定位的文本；`--extraction-dir` 同时导入完整包到 source 的 `parsing/`，保留旧抽取文本、更新 manifest 并重扫补充材料引用。
小 source 可同步解析，长文档和图片增强优先异步；执行与恢复按 [解析 Skill](../../document-granular-decompose/SKILL.md)。
`pypdf` 基础文本不得作为 PDF/Office/图片或复杂表格的唯一最终证据。图片描述是模型生成内容，必须核对原图，不能当作原文逐字引用。

只有 source 摘录、页码、表名、附录或可复核换算链能直接支持的内容，才能作为 source 证据。若字段依赖补充表或 source table，但当前只取得主文 PDF，应记录缺失的具体字段，例如 amount、unit basis、qref、flow identity、location/year、boundary 或 allocation；不得把 source 不可用、补充表缺失或字段未命中解释为来源已通过。


### 证据引用与正式准入

`evidence_refs` 使用当前案件根目录的相对文件路径，支持 `path`、`path#/JSON/pointer`、`path:pN`、`path:bN` 和 `path:pN:bN`。JSON pointer 按键是否存在核验，`0`、`false`、`null` 和空值均可定位。页号和块号从 1 开始；PDF 页号按真实页数核验，Markdown 需保留 `# Page N` 与 `### Block N` 标记，解析 JSON 按 `result` 列表的全局块序号和整数 `page_number` 核验。块号必须唯一；带页号的块引用必须归属该页。不支持的定位、不可读文件、越界路径和逃逸符号链接不能作为有效证据。

Agent 的 `pass`、`fail`、`not_applicable` 以及 `additional_findings` 必须带非空证据和可定位的 `evidence_refs`。正式 `semantic-review` 同时核对 `review_id`、`dataset_id`、`dataset_type` 和案件证据根目录；身份不匹配时整份 Agent 文件隔离，单条引用无效时隔离该记录，其余有效记录保留原始索引。没有案件根目录的独立契约校验仅报告结构有效，不能称为证据已验证。

来源核验只接受 `matched`、`conflict`、`not_applicable`、`ambiguous`、`not_found`。每条 `field` 必须绑定 `claims.json` 的实际字段；提供 `dataset_value` 时必须与 claim 值一致。`matched`、`conflict`、`not_applicable` 的 `checked_source_id` 或 `source_ref_id` 必须映射到当前案件的可读来源文档，两者同时提供时必须一致，并提供 `evidence` 或 `matched_excerpt`；`not_applicable` 还必须在 `confidence_reason` 或 `notes` 解释适用性。可通过 `evidence_refs` 引用该来源目录中的 JSON、页、块等证据；旧格式未给 `evidence_refs` 时引用已识别来源的抽取文档，`page` 转为其 `:pN` 定位。无效记录保留在上下文中并形成核验缺口，不计入来源覆盖或冲突；所有汇总仅使用准入记录。

来源 manifest 的抽取路径可为相对 manifest 的路径或案件根目录内的旧版绝对路径；不能越界，也不能按 basename 回退到另一文件。`source_documents_read` 只认可来源文档的完整案件相对路径，文件名或后缀匹配不能确认已读全文。

定位有效只说明证据位置存在。Agent 或审核员仍需判断原文是否支持当前结论，不得把路径有效或摘录字符串命中当成语义支持。

### 模型定量参考与关联过程审核索引

TIDAS 模型的 `lifeCycleModelInformation.quantitativeReference.referenceToReferenceProcess` 指向 `technology.processes.processInstance.@dataSetInternalID`。实例可以是 object 或 array；不同实例可以引用同一过程 UUID。实例的 `@multiplicationFactor` 与关联过程的 `quantitativeReference.referenceToReferenceFlow`、基准交换数量和实际单位依据共同解释模型目标量，不额外要求虚构 `targetQuantity` 字段。连接使用 `connections.outputExchange.@flowUUID` 和 `downstreamProcess.@id/@flowUUID`；输出交换和下游记录均支持 object/array。单实例模型没有 connections 合法，连接两端流 UUID 不同本身不是错误；关键性、替代和有意排除仍按模型审核方法由 Agent 判断。多个需审实例没有连接定义时，结构证据尚不充分。

Runtime 使用模型案件内的 `agent-review/model-process-audits.json` 显式引用已审过程证据，不扫描其他案件。最小结构如下（路径均为当前模型案件相对路径）：

```json
{
  "schema_version": "tiangong-audit-model-process-audits-v1",
  "audit_scope": "full-lca-semantic-review",
  "process_audits": [{
    "process_id": "过程UUID",
    "version": "01.00.000",
    "snapshot_path": "snapshots/linked-processes/process.json",
    "snapshot_sha256": "64位小写SHA256",
    "report_path": "agent-review/imported/process.semantic-review.json",
    "reference_unit": {
      "unit": "kg",
      "evidence_refs": ["snapshots/flow-units.json#/reference_unit"]
    }
  }],
  "node_roles": [{
    "instance_id": "非参考实例内部ID",
    "is_key": false,
    "reason": "据实际边界和连接说明此实例为何非关键",
    "evidence_refs": ["snapshots/dataset.raw.json"]
  }]
}
```

- 每个需审的过程 ID/版本须有唯一索引项。参考实例始终关键；未分类实例按需审处理。非关键角色须有理由和可定位证据，仍须提供过程对象、基准流、量/单位和连接的基本证据，只免完整过程审核报告。关键性和角色匹配须在模型 Agent 必审项中显式判断。
- `snapshot_path` 可引用案件内 JSON，必须与 intake 留存的当前 `snapshots/linked-processes/` 对应 ID/版本快照内容一致；缺少本轮快照不能用自洽旧报告替代。包装 API 行和原始 TIDAS 均可识别；已提供的外层与内层身份不得矛盾。`snapshot_sha256` 对解包后的 TIDAS JSON 以 UTF-8、`ensure_ascii=false`、键排序、分隔符 `(',', ':')` 计算，不依赖缩进或平台行元数据。新 semantic-review 报告提供同算法的 `dataset_snapshot_sha256`。
- `report_path` 的物理位置不固定，但须是当前案件内可读取的完整过程 semantic-review 报告，绑定相同 ID、版本和快照 hash，包含正式 schema、`review_task_id`、`dataset_type: process`、完整 `audit_scope`、有效 Agent 必审覆盖、`audit_completeness`、来源/规则两层结论及 `findings`。只有 `complete: true` 的裸摘要、错误版本或局部报告不能作为关键过程已审证明。旧报告没有 snapshot hash 时，可额外提供 `context_path` 引用该次报告的 semantic-context；其 review_id、数据集身份及 dataset_raw hash 必须一致，否则保留审核缺口，不自动补造证据。
- 原始 TIDAS exchange 通常不带单位字段。`reference_unit` 用实际流/属性/单位证据补充解释，不强制在原始交换中新增 unit；Agent 仍须核查证据内容是否支持所填单位。参考实例缺少量/单位依据为信息缺口；复杂参数、额外 scalingFactors、零值或负值缩放留人工确认，Runtime 不冒充完整 LCA 计算器。
- 关联过程预检阻断项、或已审过程发现的模型影响不明时留人工确认；只有经证据确认的模型级问题形成模型阻断，不自动将过程问题上传为模型错误。局部请求使用 `audit_scope: partial`，报告保留局部范围，`audit_completeness.complete` 为 false，不能生成完整通过。
