# 平台操作流程

审核判断与平台操作是两条独立流程。先形成并由人工确认审核结论，再执行平台动作。

## 读取待审核数据

查看待审核队列、拉取单条 review 任务、读取过程或模型数据集、追踪 source dataset 和下载
`external_docs`，默认都使用管理员账号 `admin`。不要用审核员账号作为日常查看待审核数据入口。

只有在写回建议、暂存通过报告、提交审核意见或其他需要平台身份语义的写入动作时，才区分：

- `reject`：驳回/退回建议草稿语义角色，默认使用管理员账号。
- `pass`：通过报告和验证审查草稿语义角色，默认使用审核员账号。

## 通过流程

审核结论确认为“通过”后，默认平台动作仍然只是保存草稿：

1. 确认 `semantic-review` 报告结论为“通过”，且平台退回意见为“无”。
2. 使用 `pass` 语义角色创建或上传本次完整审查报告 source；该角色默认使用 `.env` 中配置的审核员账号（`TIANGONG_MEMBER_EMAIL`）。
3. 在待审核数据中填写验证审查和合规性声明并关联本次报告 source。
4. 调用 `app_review_save_comment_draft` 保存草稿，不调用 `app_review_submit_comment`。
5. 本流程不得调用 `cmd_review_assign_reviewers`，不得提交审核意见，不得执行管理员通过或驳回。

分配审核、提交审核意见、管理员最终通过或驳回都是改变任务状态的独立动作，必须在本轮审核结论之后另行获得明确授权。

## 通过报告来源

创建“完整审查报告”来源数据集时，使用 `assets/approval-report-template.docx` 的固定格式，只替换以下字段：

1. 数据集名称。
2. 数据集 UUID 和版本号。
3. 数据集位置，例如永久 URI、URL、联系点或数据库名称和版本。
4. 审查方法及范围。

来源信息使用：

- 源的简称：`过程“{数据集名称}”审核报告`；模型数据集使用 `模型“{数据集名称}”审核报告`。
- 分类：出版物与通信。
- 出版类型：个人书面交流。
- 数据集拥有者：`a1d95758-6904-4802-a061-fedc6ac4b4b4`。

## 过程数据通过流程

当用户要求“对某条数据操作通过流程”“执行通过流程”“已通过数据走流程”等动作时，过程数据执行本流程。生命周期模型数据执行下方“模型数据通过流程”；不得把过程数据的范围名称、链接或审查详情硬套到模型数据。

高风险歧义约束：

- 用户说“待审核里的过程数据通过”“通过审核”“进行通过审核操作”“把待审核过程数据都通过”时，默认含义是本节固定流程：生成本次 DOCX 完整审查报告、创建本次 source、暂存验证审查和合规性声明。
- 上述说法不得解释为提交审核意见，不得调用 `app_review_submit_comment`，不得使用 `submit-result`，也不得把任务从 member 待审核队列移入已审核队列。
- `app_review_submit_comment` 是审核员提交动作；调用后会从 member 待审核队列移入已审核队列，并进入管理员侧后续处理，不是本节的“过程数据通过流程”。
- 只有用户明确说“提交审核意见”“提交审核结果”“从待审核移到已审核”“现在提交到管理员确认”，并且已完成本节暂存和读回验收后，才允许另行评估提交动作。

### STOP/CHECKPOINT

执行任何写入前必须完成以下检查；任一项不满足时停止，不创建来源、不上传文件、不暂存评论：

- 当前任务可读取，且当前账号是该任务的分配审核员。
- 数据集已确认是过程数据，原始结构包含 `processDataSet`。
- 用户已明确该数据为通过数据，且本次只需要平台暂存通过流程。
- 已取得建模信息-数据集类型，并能映射为中文范围名称。
- 已确认 DOCX 报告来源将由 `pass` 语义角色创建；该角色默认使用审核员账号，且该账号必须是当前任务允许的分配审核员。

前置确认：

1. 从审核队列或指定 ID 读取任务，确认任务存在且当前账号是该任务的分配审核员。
2. 拉取数据集，确认类型为过程数据，原始结构包含 `processDataSet`。
3. 确认该数据已由人工判定为通过；本流程只做平台暂存/报告来源创建，不重新生成通过结论。
4. 读取“建模信息-数据集类型”，过程数据原始字段通常为 `modellingAndValidation.LCIMethodAndAllocation.typeOfDataSet`，并映射为中文名称：
   - `Unit process, single operation` -> `单元过程，单一操作`
   - `Unit process, black box` -> `单元过程，黑箱`
   - 其他值缺少明确映射时停止并请求人工确认中文写法。

写入顺序：

1. 基于 `assets/approval-report-template.docx` 生成本条数据的 DOCX 审查报告，只替换数据集名称、数据集 UUID 和版本号、数据集位置、审查方法及范围、审查完成日期。
2. 审查方法及范围写作 `{建模信息-数据集类型中文名称}；质量平衡`。
3. 审查完成日期使用执行当天日期，格式沿用模板，如 `2026年6月23日 23/6/2026`。
4. 使用 `pass` 语义角色上传 DOCX 到 `external_docs/{uuid}.docx`；不得用非分配审核员账号创建报告文件。
5. 使用 `app_dataset_create` 创建 `sources` 数据集，`jsonOrdered.sourceDataSet` 必须包含：
   - `publicationType`: `Personal written communication`
   - `common:shortName`: `过程“{数据集名称}”审核报告` 及英文名称
   - `referenceToDigitalFile.@uri`: `../external_docs/{docx_uuid}.docx`
   - 分类 `Publications and communications`
   - 所有者 `a1d95758-6904-4802-a061-fedc6ac4b4b4`
6. 使用 `app_review_save_comment_draft` 暂存验证审查和合规性声明，验证审查字段必须包含：
   - 审查类型：独立外部审查
   - 范围名称：建模信息-数据集类型中文名称
   - 方法名称：质量平衡
   - 审查详情：中英文均填写
   - 完整审查报告：本次创建的来源数据集
   合规性声明必须采用已审核参考数据 `0a263660-a557-491a-ab58-bdf6f9222765` 的 5 条合规系统声明样板，不得简化为单条 ILCD Entry-level 或六项全 `Fully compliant`。
7. 本流程只能使用 `app_review_save_comment_draft` 保存草稿；不得使用 `app_review_submit_comment` 或任何会完成审核员提交的接口。换言之，只能使用 app_review_save_comment_draft，不能提交审核意见。

读回验收：

1. 重新读取 `comments`，确认 `state_code=0`。
2. 确认 `modellingAndValidation.validation.review[0].common:scope[0].@name` 等于建模信息-数据集类型中文名称。
3. 确认 `common:scope[0].common:method.@name` 为 `质量平衡`。
4. 确认 `common:referenceToCompleteReviewReport.@refObjectId` 是本次创建的 source ID。
5. 重新读取 `sources`，确认 source 的 `user_id` 是当前分配审核员账号，且 `referenceToDigitalFile.@uri` 指向本次上传的 DOCX。
6. 不自动提交审核；只暂存，除非用户另行明确要求提交。

## 模型数据通过流程

模型数据通过流程复用过程数据通过流程的上传 DOCX、创建 source、保存草稿、读回验收机制。差异只保留模型必需字段：

- 只适用于 `lifeCycleModelDataSet`，命令使用 `model-pass-flow`。
- 数据集位置使用 `datasetdetail/lifecyclemodel.xhtml?uuid={uuid}&version={version}`。
- 源的简称使用 `模型“{数据集名称}”审核报告`。
- 审查方法及范围写作 `生命周期模型；质量平衡`。
- 验证审查范围名称写作 `生命周期模型`，方法名称写作 `质量平衡`。
- 审查详情围绕模型目标、定量参考、模型结构、关联过程和主要连接关系填写。
- 合规性声明复用过程通过流程的 5 条合规系统声明样板。
- 仍然只能使用 `app_review_save_comment_draft` 保存草稿，不得提交审核意见。

## 验证审查暂存

填写“审核过程-验证审查”时：

- 审查类型：独立外部审查。
- 范围名称：过程数据必须取“建模信息-数据集类型”并写成中文名称；过程数据集平台原始字段通常为 `modellingAndValidation.LCIMethodAndAllocation.typeOfDataSet`。例如 `Unit process, single operation` 写作 `单元过程，单一操作`，`Unit process, black box` 写作 `单元过程，黑箱`。模型数据写作 `生命周期模型`。不得把范围名称固定写成某个默认值。
- 方法名称：质量平衡。
- 审查详情：中英文都要填写，说明对象、边界、参考流或目标量、主要清单或模型结构与通过判断。
- 完整审查报告：选择本次为该数据集创建的来源数据集。
- 暂存后重新读取评论，确认 `comment_state_code=0` 且完整审查报告引用的 `@refObjectId` 为本次创建的来源 ID。

## 不通过流程

1. 汇总已验证的阻断问题。
2. 将建议修改与阻断问题分开。
3. 确认意见包含一句话修改建议。
4. 生成平台退回意见和待执行操作清单，到此停止。

## 驳回建议草稿暂存

当用户明确要求“驳回建议写回”“退回建议保存草稿”“把退回意见写到平台草稿”等动作时，只能使用 `reject` 语义角色调用 `app_review_save_comment_draft` 保存评论草稿。该角色默认使用 `.env` 中配置的审核管理员账号（`TIANGONG_ADMIN_EMAIL`）。

该流程的边界：

1. 只写评论草稿，不提交审核意见。
2. 不调用 `app_review_submit_comment`。
3. 不调用管理员驳回或退回接口。
4. 不改变任务队列状态。
5. 写入前必须先 dry-run 生成 payload，并由用户确认内容无误。

推荐命令：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<batch-id>/reviews/<review-id>/reports/audit-result.platform.json
```

确认无误后：

```bash
uv run python -m tiangong_audit.cli save-result-draft \
  --result cases/active/<batch-id>/reviews/<review-id>/reports/audit-result.platform.json \
  --execute
```

### 不通过写入 STOP/CHECKPOINT

当前阶段，Agent 在审核得出“不通过”“信息不足”或“需人工确认”结论后，不得自行执行管理员驳回、退回修改、提交审核意见或任何会改变任务状态的写操作。

只有在已经形成审核结论之后，用户另行明确要求执行平台驳回或退回修改，例如“执行驳回”“退回这几条”“把这些不通过项在平台驳回”“现在提交退回意见”，才允许调用 `cmd_review_reject` 或同类写接口。用户仅要求“审核”“按流程审核”“处理第一页数据”“生成退回意见”“不通过的给意见”等，都不是驳回授权。

执行驳回前必须再次确认：

1. 待驳回任务 ID 与本轮报告一一对应。
2. 平台退回意见来自本轮报告，且只包含已验证的问题。
3. 用户的最新指令明确要求平台驳回或退回修改。
4. 写入后读回任务，确认状态和退回意见；若读回失败，不得声称驳回完成。

## 操作约束

- 默认只提供操作清单，不自动执行平台写操作。
- 审核任务中形成“通过”结论且审核员身份已明确时，只能按上述通过流程保存草稿；不得提交审核意见。
- 上传报告、审核员提交、管理员最终通过或驳回仍须获得用户明确确认；其中“不通过”结论绝不等于驳回授权。
- 平台操作失败不得改变已经形成的审核判断。
- 不得在真实平台使用创建函数探测字段；若必须探测接口，只能使用不会创建记录的校验请求或先在非生产环境验证完整 payload。

## 禁止动作

- 不得把模型数据套用过程数据的范围名称、链接或审查详情；模型数据必须使用模型数据通过流程。
- 不得使用非分配审核员账号上传 DOCX、创建来源或暂存评论。
- 不得提交审核、管理员通过或驳回，除非用户在审核结论之后明确要求该写操作；不得把“不通过”“按流程审核”“处理这些数据”解释为驳回授权。
- 不得把“通过审核”“待审核里的过程数据通过”“全部过程数据通过”解释为提交审核；这些表述只能触发本节草稿暂存流程。
- 不得调用 `app_review_submit_comment`、`submit-result` 或直接构造 `ReviewAPI.submit_result(...)` 来执行本节流程；这些动作会从 member 待审核队列移入已审核队列。
- 不得在真实平台使用 `app_dataset_create` 或其他创建函数探测字段。
- 不得复用旧 source 或旧 DOCX 作为本次完整审查报告；每条数据创建本次专属来源。
- 不得在读回验收失败时声称流程完成。
