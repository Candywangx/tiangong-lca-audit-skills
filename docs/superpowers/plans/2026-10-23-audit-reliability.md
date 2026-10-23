# 天工 LCA 审核可靠性修改与验收方案

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复错误通过、无证据驳回与评测失真，使审核结论、证据、规则和输出可以一致复核。

**Architecture:** 保留现有分层。审核政策仍由 audit-policy.md 定义；规则适用性和必审元数据放在 rules/*.json；契约层验证记录，工作流只聚合有效发现。证据可定位由程序验证，证据是否支持判断仍由 Agent 或审核员验证。

**Tech Stack:** Python 3.11+、pytest、JSON 规则和契约、Markdown Skill；不新增在线服务依赖。

状态：T1–T5 已实施并完成分项复核；T6–T7 未实施。2026-10-23 初始工作树基线为自检通过、344项测试通过；最终集成自检通过、476项测试通过。验证及兼容记录见 `docs/audit-reliability-validation.md`。保留已有未提交改动，下述路径均相对仓库根目录。

实施授权：用户已授权先执行 T1–T5；T6–T7 不在本轮修改范围。

Representation Decision：审核记录与证据引用属于供 CLI、工作流、报告和审核员共同消费的 F3 契约。自然语言 evidence/judgment 保留表达自由；仅将文件/条目有效性、规则适用性配置及证据定位验证结构化。定位有效不晋升为语义真实，最终签字仍属人工。允许通过明确迁移更新格式，不自动补造历史证据。验证循环采用反例、合法正例、独立复核和脱敏场景；若新增字段不能阻止已复现错误或支持真实消费者，撤回该额外约束。

## Chunk 1 修改目标与实施边界

按 T1 → T2 → T3 → T4 → T5 → T6 → T7 实施。T2 和 T3 共用规则元数据与证据解析，应合并设计、分别验收；T4 使用前三项能力。

每项统一实施步骤：

- [ ] 将下表失败样本写成脱敏回归，先确认旧实现确实失败；已有通过行为保留正例。
- [ ] 实现最小改动，不重写无关 API、平台操作或解析流程。
- [ ] 执行该项测试，并检查旧通过样本、合法例外没有被误拒。
- [ ] 更新唯一事实来源和对应导航/模板；不在多个文件复制规则条件。
- [ ] 按项形成可审阅 diff；不得将用户原有改动混入无关提交。

核心验收原则：缺证据不等于数据错误；有其他有效阻断时，即使还有信息缺口，也必须维持不通过。补齐格式不证明语义正确。任何新关卡都要有合法通过样本，不能靠一律拒绝通过验收。

### T1 隔离无效审核意见

**目标：** 无效意见不参与结论、覆盖率或平台退回意见；其他独立有效发现仍被保留。

**修改文件：** `src/tiangong_audit/contracts/agent_review.py`、`src/tiangong_audit/workflows/semantic_review.py`；测试 `tests/test_agent_review.py`、`tests/test_semantic_review_workflow.py`、`tests/test_platform_opinions.py`。

**具体做法：** 将文件级错误和逐条记录错误区分。内部校验结果携带记录 JSON pointer、错误原因和有效性，保留现有返回错误列表的公共入口兼容。rule_reviews 与 additional_findings 使用相同准入原则；记录无效时保留原文和诊断，但排除正式 finding 与平台意见。文件身份或整体结构不可验证时隔离该文件全部判断。summary 的“已填写”与“有效覆盖”分开，不能继续把无效记录算完整。

| 验收样本 | 可接受结果 |
| --- | --- |
| 其余检查均通过，唯一 fail/blocking 缺 evidence/refs | 原条目隔离；出现审核记录信息缺口；结论信息不足，不能不通过或通过；平台意见不要求提交者修改该无证据问题 |
| 一条无效阻断，另一条证据充分的真实阻断 | 结论仍不通过；只保留有效阻断的修改意见 |
| 无效 additional_findings 阻断 | 与无效 rule_reviews 同样隔离 |
| 全部意见有效、所有核心检查完成 | 保持通过；原有效失败样本保持不通过 |

补充准入范围：`source-checks/checks.json` 的 conflict 发现也须经过证据准入；不能仅修复 Agent 文件而保留 source conflict 的无证据阻断入口。缺来源、缺可核验摘录/定位的 conflict 应形成核验缺口，而不是已验证阻断；有完整证据的 source conflict 必须继续生效。

### T2 约束不适用豁免并统一必审目录

**目标：** 保留合法 not_applicable，禁止用笼统“不适用”绕过对象、数量、边界等核心审核。

**修改文件：** `skill/tiangong-lca-audit/rules/schema.json`、`rules/process.json`、`rules/model.json`、按需 `rules/common.json`；`src/tiangong_audit/contracts/agent_review.py`、`contracts/schemas/agent-findings.schema.json`、`rule_engine/engine.py`；`references/audit-policy.md` 仅定义通用豁免原则；测试 `tests/test_rules.py`、`tests/test_agent_review.py`、`tests/test_rule_engine.py`、`tests/test_semantic_review_workflow.py` 和脱敏评测案例。

**具体做法：** 在规则中增加明确的必审元数据和是否允许 not_applicable 的元数据；豁免条件复用该规则已有 condition/exceptions，不再创建另一套自然语言条件。移除 Python 中手工维护的必审 ID 表，预检、模板和校验统一从规则目录读取。逐条审定适用范围，不机械把全部规则设为不可豁免。允许豁免时必须提供具体理由、证据和有效引用；理由对应的业务条件由语义复核确认，不能靠字数或关键词通过。不确定适用性时使用 cannot_judge，按信息缺口/人工判断分流。

| 验收样本 | 可接受结果 |
| --- | --- |
| 全部核心规则 not_applicable，只有“不适用”理由 | 无效且有效覆盖不完整，不能通过；不是数据集错误驳回 |
| 明确不可豁免规则，即使填写理由与引用 | 不接受豁免；要求完成该核心检查 |
| 一条确有条件性例外的规则，输入证明满足其例外，其他检查完成 | 豁免被接受，不制造阻断，可通过 |
| 缺少判断适用性的证据 | cannot_judge；核心证据缺失为信息不足，业务解释不确定为需人工确认 |
| 修改目录的必审标记 | 模板、预检和覆盖校验同步变化；无第二份硬编码清单 |

实施时必须在回归样本中指定真实规则 ID、例外条款和对应输入；“合法例外”不能停留在抽象描述。规则变更需同时记录适用范围、反例和旧行为过宽的复现依据。

### T3 验证证据引用可定位

**目标：** 引用真实、可读取并能定位；拒绝不存在的文件、空引用和伪造页码，但不将路径有效误称为内容已证实。

**修改文件：** 新增 `src/tiangong_audit/contracts/evidence_ref.py` 统一解析；修改 `contracts/agent_review.py`、`workflows/semantic_review.py`、`cli.py` 的案件校验入口；契约定义放 `skill/tiangong-lca-audit/references/input-contract.md`；测试新增 `tests/test_evidence_refs.py` 并扩展 Agent/工作流测试。

**具体做法：** 实施前盘点脱敏 fixture 和代码里的引用语法，明确支持的案件相对路径、JSON pointer、页/块定位形式。有效旧格式通过适配器兼容；不支持的格式给出可迁移错误，不静默当普通文件名。引用必须绑定当前案件证据根目录；禁止越界和借符号链接逃逸。页码以来源页数或带页标记的解析证据核验，不按纯文本行数猜测。无法验证的定位标记为未验证，不能支撑有效 pass/fail。结构校验无 case_root 时只能报告结构有效，正式 semantic-review 必须完成上下文引用校验。无需为所有直接字段证据强制 PDF 页码；dataset JSON 指针同样是合法证据。

| 验收样本 | 可接受结果 |
| --- | --- |
| refs=[空字符串]、不存在文件、无效 JSON pointer | 定位失败且该判断无效，不能计入通过覆盖 |
| 文件存在但引用 p999 超过可核验页范围 | 定位失败，不因文件存在放行 |
| 文件存在，但没有能确认所引页码的证据 | 明确未验证，要求可定位证据；不伪称不存在该页 |
| 当前案件文件及有效 pointer/页/块 | 校验通过，不误拒 JSON、中文路径等合法证据 |
| 引用 ../其他案件 或越界符号链接 | 拒绝引用，不读取根目录外内容 |
| 引用位置存在但语义不相关 | 结构检查可通过；Agent 对照用例必须判“不支持”，不能仅凭定位成功判通过 |

同样覆盖 `source-checks/checks.json`：matched、conflict、not_applicable 必须绑定实际 claim 和可核验来源/适用性证据，使用统一引用解析；未经验证的 matched/not_applicable 不计 source 覆盖，未经验证的 conflict 不计阻断。扩展 `tests/test_sources.py` 和 semantic-review 测试，加入“来源不存在”“p999”“无支持摘录的 conflict”“无依据的 not_applicable”反例及合法 matched/conflict 正例。验收结果分别为核验缺口、核验缺口、核验缺口、未完成覆盖，以及合法支持可通过/合法冲突仍不通过。不得因此强制每种 source 都有 PDF 页码；JSON/table/block 等可定位证据同样接受。

### T4 补齐模型最低输入和完整审核关卡

**目标：** 模型必须完成目标、结构、关键过程、整体一致性和质量证据审核；仅有模型名称与关联 ID 不可通过。

**修改文件：** `workflows/semantic_review.py`、必要的 `normalizer/projected.py`、`contracts/agent_review.py` 规则加载；`rules/model.json`、`references/model-audit.md`；测试 `tests/test_normalizer.py`、`tests/test_semantic_review_workflow.py`、`tests/test_rules.py` 和模型脱敏案例。

**具体做法：** 真正执行已有 model.core.input_coverage 所规定的最低输入检查；通过规则元数据覆盖目标一致性、角色匹配、边界方法、质量信息。节点连通的纯图判断与“关键节点/合理排除”等语义判断分开，后者不得伪装确定性规则。每个关键关联过程必须有绑定过程 ID/版本及证据快照的有效审核记录，单纯存在 JSON 或 Agent 一句 pass 不算已审核；不强制特定物理目录，允许经契约校验的导入审核摘要。关联过程问题是否传导到模型仍需解释，不自动一票否决。局部审核必须显式标注范围，不能导出完整通过。

| 验收样本 | 可接受结果 |
| --- | --- |
| 只有模型名称、关联 ID/version，以及一条 linked_process.audit=pass | 信息不足；列出目标量、结构、关键过程可审数据/审核缺口；完整审核状态为 false |
| 有模型结构，但关键过程未审或摘要版本不匹配 | 信息不足，不认可过期/错版本摘要 |
| 目标量、结构、关键过程与所有核心语义审核完整 | 通过，完整审核状态为 true |
| 有完整证据证明关键路径断开且影响目标 | 不通过，并定位相关节点/连接 |
| 经证据确认的有意排除节点 | 不机械判阻断；按规则例外处理 |
| 用户仅请求结构局部审核 | 可以完成局部检查；不得标成模型完整通过或生成完整通过草稿 |

### T5 修正评测器与验收样本

**目标：** 区分“提到规则”与“正确识别问题”，同时测量漏判、误判、建议缺失和结论矛盾。

**修改文件：** `src/tiangong_audit/evals/harness.py`、`cli.py` 的 eval 命令；`tests/evals/audit-evaluation-cases.json`、`tests/test_evals.py`、`tests/test_cli.py`。

**具体做法：** rule_id 仅用于候选匹配，不自动算命中；每个问题点有独立身份和所需证据/位置/建议检查。shouldMentionSuggestion 真正参与评分。同规则多个问题点必须分别匹配具体证据；允许一条合并意见覆盖多个问题，但须分别满足各点证据。评分增加错误意见、结论与严重程度矛盾及建议完整性；通过样本也配置禁报问题。无法自动判断的自然语言匹配标记待人工复核，不默认为通过。旧 issue_point_coverage 保留兼容说明，但验收不得单独依赖该指标。已知反例和结论矛盾是硬失败，不允许平均分抵消。

| 验收样本 | 可接受结果 |
| --- | --- |
| 只有 rule_id，无证据、无建议 | 有效问题覆盖为0，验收失败 |
| 同一规则对应三个不同问题，只写出其中一个 | 只能覆盖实际证实的一个，不能3/3 |
| 合并意见确有三个问题的各自证据和动作 | 可以覆盖3/3，不为凑数强迫拆分 |
| 结论通过，却有 blocking | 结论一致性硬失败 |
| 正确通过样本夹带“非必填空值必须修改” | 误报被检出，验收失败；不能靠写通过结论蒙混 |
| 正确问题、证据与可执行建议齐全，无额外误报 | 对应评测项全部通过 |
| 自然语言等价表达而非关键词原样复述 | 不以关键词缺失直接判漏报；进入支持的匹配或人工复核 |

### T6 闭合分发依赖和无 Runtime 路径

**目标：** 从主 Skill 安装后能明确知道需要什么、能完成什么；无需依赖维护者仓库的隐含目录结构。

**修改文件：** `skill/tiangong-lca-audit/SKILL.md`、`references/input-contract.md`、`references/platform-operations.md` 中导航；`docs/quickstart.md`、`README.md`；新增 `tests/test_distribution.py`。

**具体做法：** 明确两条支持路径：主 Skill 单独分发可基于已提供的可定位证据进行人工辅助审核；完整自动化包需显式安装解析 Skill 和 Runtime。纯 Skill 路径使用同一输入/输出契约记录证据与结论，不强制虚构案件 JSON 或 CLI 调用。完整审核仍遵守平台题目查重证据关卡；无法满足时只能整理输入和报告受限范围。需要高保真解析而依赖不可用时给出具体缺口，不能用低保真结果假装满足要求。不要把整个 src 复制进 Skill，也不要维护两份解析 Skill。

| 验收样本 | 可接受结果 |
| --- | --- |
| 临时目录仅复制主 Skill，切断对仓库其他目录访问 | 内部资源可达；外部依赖明确标记；具备完整外部证据时可按文档人工审核，无隐藏 CLI 要求 |
| 缺解析依赖/凭据或平台查重证据 | 指出具体限制，不崩溃、不捏造通过、不绕过现有关卡 |
| 主 Skill+解析 Skill+Runtime 按说明安装 | 导航/命令 smoke test 可用，完整流程使用脱敏 mock 走通 |

### T7 对齐模板和输出契约

**目标：** 使用官方模板即可满足两层结论和最终综合结论的强制要求。

**修改文件：** `skill/tiangong-lca-audit/assets/audit-result-template.md`；按需同步 `src/tiangong_audit/report/markdown.py`；测试 `tests/test_assets.py`、`tests/test_skill_contract.py`、`tests/test_platform_opinions.py`。

**具体做法：** 增加 source 一致性、规则符合性和综合结论槽位；状态与写作依据引用 output-contract.md，不复制完整政策。检查手工模板和程序渲染结果都具有这些部分。

| 验收样本 | 可接受结果 |
| --- | --- |
| 通过/不通过/信息不足/需人工确认各一份输出 | 每份均有两层结论、综合结论、范围和平台意见；聚合符合政策 |
| 证据缺口来源为工具失败 | 只限制审核结论，不自动生成提交者补交义务 |
| 平台意见超过1000字或遗漏有效阻断 | 明确拒绝完成稿，不截断遗漏；原有限额和标识测试保持通过 |

## Chunk 2 最终验收与交付

**自动化验收：** 下列命令退出码均为0。环境没有 python 别名时使用 python3，含义相同。

```bash
PYTHONPATH=src python3 -m tiangong_audit.cli check
PYTHONPATH=src python3 -m pytest -q
```

分项可使用 `PYTHONPATH=src python3 -m pytest -q <上述测试文件>`。不固定最终测试数量，但现有344项中每项行为变更必须说明原因，不允许通过删除反例或降低断言隐藏回归。每条通用规则变更至少具备一个通过样本和一个不通过/不满足规则样本；信息缺口和豁免另外覆盖。

**Agent 实测验收：** 在临时目录使用完整脱敏字段和实际可读取证据，补足上一轮只有文字前提的合成测试。固定三组包：A 正常过程含非必填空值、未审核流、基准流100%；B 缺关键过程和补表的模型；C 甲正常、乙数量差1000倍的批量。每组跑两次独立会话，记录提示、输出、模型/运行环境和证据包版本。六次均需满足预设结论、范围和平台操作边界；不得编造字段/页码；C必须定位实际字段、原值、单位、来源位置和换算方向。B只有确认提交资料确实缺失时才能要求提交者补交。措辞可变化，事实与严重程度不得变化。所有平台写工具用 mock，断言调用次数为0。

**交付清单：** 逐项 diff、反例修复前/后结果、自动化测试输出、六次 Agent 场景输出及复核结论、分发 smoke test 记录、兼容/迁移说明。真实案件不提交。新格式导致旧记录无法通过时列出迁移方法；不得为使历史案件重新通过而自动补写语义证据或批量改真实案件。

**接受门槛：** T1–T7 表中所有条件满足；修复的错误通过和无证据驳回均不可再现；合法通过、合法豁免保持可用；文档不引入重复规则源和隐含依赖。Darwin评分提高不是验收条件，测试全绿也不能代替场景复核。

**阶段交付：** 第一阶段T1–T4阻断错误结论；第二阶段T5提高评测可信度；第三阶段T6–T7闭合分发与输出。各阶段独立审阅，最终完成仍要求全部验收通过。本方案不授权任何平台写入。
