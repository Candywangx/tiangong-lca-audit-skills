# 专家审核角色与三人组队实施计划

> 使用 superpowers:subagent-driven-development 实施并独立复核。用户已批准角色标注、规则调整、历史回归、新案件盲测及少量待审任务推荐；没有授权分配、修改角色、网页接入或自动化动作。

**Goal:** 将专业行业和审核职责分开，以有证据的行业、LCA方法、数据/建模角色组成可解释的三人建议，保持明确的人工确认边界。

**Architecture:** Agent 为专家生成有范围、引文、局限的角色证据；程序验证完整性、来源和三位不同人的职责组合，不自行推断专业能力。已有v1输入/结果保留，新角色上下文和结果使用v2，禁止降级绕过角色检查。

**Tech Stack:** 现有Python/JSON/pytest、私有快照、只读平台API、独立Agent评测。

## 表示选择

角色为F2语义投影：domain、method、data_model，逐项记录supported/conditional/insufficient、scope、evidence和limits。supported只表示资料有对应经历，不是资格认证或全领域能力。身份和版本绑定为F3；分配仍为单独的人工确认后操作。

角色档案根对象为 `tiangong-expert-roles-v1`，`input_sha256` 绑定按expert_id排序的专家原文投影（expert_id、fields_text、experience_text），`profiles` 精确覆盖输入专家。各profile包含expert_id及三项roles；角色项包含role、support、scope、evidence（field/quote）和limits。supported须有experience_text引文；纯行业标签不能证明方法/建模经验。

上下文v2嵌入已验证role_profiles。推荐v2每位候选增加primary_role、responsibility、suitability（supported/conditional）；每案增加team_rationale。primary_role是本次主职责，不改变专家具备多种能力的事实。程序检查职责是否显式分配，具体适用性仍由Agent/人工判断。

三人proposed须三位不同且角色与本次适配均有支持。过程默认两位domain加一位method；不同组合须解释composition_exception，但仍至少覆盖domain和method。模型须覆盖domain、method和data_model。有条件人选、缺关键角色或证据缺口可以保留为needs_context/insufficient_candidates，不能标为完整三人建议。不把缺口包装成数据审核blocking。

## Chunk 1 角色原文与纠偏

- [x] 在私有目录记录旧判断、首轮模型漏配证据、适用范围及反例。
- [x] 为既有53位合格专家逐项标注三类角色，并独立核对引文、范围和局限；无“所有行业全能”标签。
- [x] 真实档案、名单、引用与试验只保存cases/expert-directory/，公开文件只含通用方法和脱敏样例。

## Chunk 2 契约、命令和方法

文件：新增src/tiangong_audit/experts/roles.py、tests/test_expert_roles.py；修改experts/recommendation.py、context.py、expert_commands.py、tests/test_expert_recommendation.py、tests/test_expert_cli.py。

- [x] 先验证缺失职责/无行业能力/伪造引文/低版本绕过等失败，再实现最小角色和v2验证。
- [x] roles-validate验证专业投影；prepare可接roles文件，强绑定专家原文；validate支持v1历史与v2新结果。
- [x] 角色profile覆盖必须完整、唯一；方法和建模role的适配依据不得由行业名单字符串自动生成。
- [x] 修改expert-selection.md为按职责选择和团队覆盖；保持platform-operations.md中逐任务人工确认要求。
- [x] 增加方法专家跨行业正例、方法专家不能代替核心工艺反例、模型角色组合及conditional保留测试。

## Chunk 3 回归、新盲测与真实任务

- [x] 原20案作为历史回归；首轮冻结结果不改。另用相同完整输入运行旧行业门槛与新角色方法，区分输入修复和规则变化的影响。
- [x] 选择至少10个此前未用于推荐的案件，按数据集ID/内容去重，排除简单改名/同内容版本，明确行业覆盖局限，冻结输入。
- [x] 新盲测推荐者与独立评审者不互读结果，输出后再逐项复核角色适配和团队覆盖；不得用名单完全相同作为唯一标准。
- [x] 比较三人建议数、支持/有条件/无依据配对、角色覆盖缺口及不必要弃选；不把Agent评估当人工准确率。
- [x] 只读检查当前待审任务，选少量新任务给出角色、理由、局限及候选；没有可用任务则如实记录，不用历史任务冒充当前任务。

## Chunk 4 验证与交付

- [x] 独立规格与代码复核；自检、全量测试、git diff --check与隐私扫描通过。
- [x] 确认既有冻结产物未变、真实文件全部忽略、待提交文件无真实姓名/邮箱/电话。
- [x] 代码本地整合；交付私有角色名册、回归对比、新盲测及真实任务建议；不推送GitHub，不执行平台分配。

## 实际交付与限制

角色53人×3项，独立复核修订1项。相同完整证据20案的共同口径复核支持完整三人组旧5、新13；原执行者声明proposed分别12与10，单列保存。新10案原选完整组1案，揭盲后另有2案替代见证，不回填原分数。

当前任务初始3例中1例在交付前发生状态与内容变化，已作废旧建议并补选独立新例。当前2组完整建议、1组保留行业条件，均未执行分配。评测后澄清边界，通过4个独立脱敏正反语义回归；原试验输入、策略与结果不改。自检、682项测试及规格/质量复核通过。详见docs/expert-role-team-validation.md，真实记录只在私有目录。
