# 输入契约

## 1. 可接受输入

- 天工 API 原始 JSON。
- 已投影为窗口结构的 JSON。
- 模型数据与关联过程数据包。
- 页面截图或用户描述；此类输入通常只能做局部审核。
- 已有审核意见、报告草稿或人工纠偏。

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

平台 raw 过程交换通常只提供流 UUID 和版本，不等于已取得流类型与分类。Runtime 必须先按 UUID + 明确版本查询关联 `flows` 数据集、保存关联流证据并生成 enriched 快照，再执行标准化和预检；引用缺少版本时不得自行选择任意版本。标准化交换使用 `flow_metadata_status` 区分 `resolved`、`not_fetched`、`not_found`、`fetch_failed` 和 `parse_failed`：只有 `resolved` 后字段仍为空，才可判断流元数据确实缺失；其他状态属于审核证据采集缺口，不得写成提交者未填写。模型审核取得的关联过程也适用同一补全步骤。

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
- `sources/*/manifest.json`：source 下载、hash、抽取状态、错误信息，以及 `related_artifact_requirements` 中列出的补充材料追踪要求。PDF/Office/图片或复杂表格 source 应使用项目内 `skill/document-granular-decompose` 生成 image-aware 全文，并把该全文作为当前 case 的 source 证据保存。
- `sources/*/extracted.md`：PDF、文本或 JSON source 的抽取文本。
- PDF/全文、补充材料、附录、source table、raw import 表或工程资料的本地路径、URL、checksum 或受控附件位置。
- `source-checks/claims.json`：程序抽取的待核验字段清单，只是 Agent source 语义核验的输入，不是核验结论；过程数据必须把所有输入/输出交换的方向、名称、数量和单位等可见字段纳入 claims，不得只抽取参考流。
- `source-checks/checks.json`：Agent 或人工阅读数据集字段与 source 原文后写出的字段级语义核验状态；不得由字符串匹配程序自动生成最终结论。

只有 source 摘录、页码、表名、附录或可复核换算链能直接支持的内容，才能作为 source 证据。若字段依赖补充表或 source table，但当前只取得主文 PDF，应记录缺失的具体字段，例如 amount、unit basis、qref、flow identity、location/year、boundary 或 allocation；不得把 source 不可用、补充表缺失或字段未命中解释为来源已通过。

`source-checks/checks.json` 中，代码必填字段只有 `field`、`dataset_value`、`source_ref_id` 和 `status`。其中 source `status` 只描述证据核验结果，`severity` 描述对审核结论的影响；`status` 与 `severity` 含义不同，不得混用。`severity` 可以显式填写；未填写时按下表默认值解析。

高质量核验内容还应在证据可得时填写 `evidence`、`page`、`notes` 和 `confidence_reason`，并可使用 `checked_source_id`、`matched_excerpt`、`rule_id` 与 `extra` 保留定位和换算信息。这些内容要求用于提高可复核性，不等同于代码必填字段；证据不可取得时应在相应字段说明原因，不得虚构摘录或页码。允许的状态/严重程度组合为：

| `status` | 允许的 `severity` | 未显式填写时的默认值 |
| --- | --- | --- |
| `matched`、`not_applicable` | 无，不形成发现 | 无 |
| `conflict` | `blocking`、`advisory` | `blocking` |
| `ambiguous`、`not_found` | `manual_review`、`advisory` | `manual_review` |
| `source_unavailable`、`download_failed`、`extraction_failed` | `input_gap`、`manual_review`、`advisory` | `input_gap` |

不在表中的状态/严重程度组合属于输入契约错误，不能静默改写。是否把该发现传达给提交者使用独立的 `platform` 路由字段，其结构与约束只在 `output-contract.md` 定义。
