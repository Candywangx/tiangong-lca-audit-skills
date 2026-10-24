# 五类审核规则边界：证据与验证记录

本轮依据用户2026-10-24确认的目标与验收标准，完善现有规则及其必要Runtime执行；规则局部评测不等于完整审核通过，真实平台、案件和平台写入不参与本轮测试。

## 固定上游依据

| 来源与固定提交 | 阅读位置 | 可吸收的边界与用途 |
| --- | --- | --- |
| platform / b94b89c7a4bb365186ec8a5d5909bc3183dec5d0 | [过程SDK提示映射](https://github.com/tiangong-lca/platform/blob/b94b89c7a4bb365186ec8a5d5909bc3183dec5d0/src/pages/Processes/sdkValidation.ts)、[对应测试](https://github.com/tiangong-lca/platform/blob/b94b89c7a4bb365186ec8a5d5909bc3183dec5d0/tests/unit/pages/Processes/sdkValidation.test.ts)、[单位转换](https://github.com/tiangong-lca/platform/blob/b94b89c7a4bb365186ec8a5d5909bc3183dec5d0/src/components/UnitConvert/index.tsx) | 区分表单缺值与非法值；用具体字段定位提示；0应被视为有值。表单required提示不独立证明领域审核阻断，转换界面也不证明任意工艺量可比。 |
| database / 00fd4a345aa40f763b789f81b073be31ed83ffaa | [公共类型契约](https://github.com/tiangong-lca/database/blob/00fd4a345aa40f763b789f81b073be31ed83ffaa/contracts/portal/portal.common-types.v1.schema.json)、[过程身份变更前守卫](https://github.com/tiangong-lca/database/blob/00fd4a345aa40f763b789f81b073be31ed83ffaa/supabase/workspace/schemas/util/functions/dataset_flow_identity_validate_process_guard/definition.sql) | required键可允许null；身份由ID和版本构成；快照漂移会使既有证据失效。守卫是特定写入流程的契约，不能将其全部字段要求推广为审核必填。 |
| web-portal / 15d8e33a80c55c92713a7c2717928228467bab06 | [比较条件](https://github.com/tiangong-lca/web-portal/blob/15d8e33a80c55c92713a7c2717928228467bab06/src/features/compare/compatibility.ts)、[LCIA响应测试](https://github.com/tiangong-lca/web-portal/blob/15d8e33a80c55c92713a7c2717928228467bab06/tests/unit/portal-lcia-compare.test.ts)、[设计边界](https://github.com/tiangong-lca/web-portal/blob/15d8e33a80c55c92713a7c2717928228467bab06/docs/design-plan.md#74-比较) | 缺行不补零，绑定精确版本和上下文，字段一致不等于科学适用性。公开能力限制不可冒充提交缺失；比较成员数等UI限制不移植为审核规则。 |

以上均为读到的代码快照，不证明线上已经部署。上游标准化数量采用十进制字符串可作为长期参考；本轮保留现有float/None消费者与raw原值，不把上游字符串规范变成数据内容驳回条件。

## 基线与失败证据

- 基线 ed07322：自检通过，476项测试通过（20.78秒）。
- 旧Runtime首轮定向测试：24失败、10通过。失败涉及0被备用量覆盖、非有限/布尔量、参考属性错误回退、内嵌流身份错配或不足、缺元数据直接阻断及混合结论。
- 变更前独立Agent读取冻结旧规则与17项证据，原始结果存于本记录关联的结果资产。未向Agent提供预期。六项局部通过、五项不通过、六项无法判断；领域结论基本符合政策，V3选择通用证据规则而未使用适用的流版本规则，属于规则映射不足。
- R3原预期错误地使用规则默认manual_review。独立规格复核确认：年份、地区和技术事实均缺少，按现有政策应为input_gap/信息不足。已记录修正理由，保留原始Agent输出；另增R4检验事实完整而代理适用性待判断的manual_review边界。

## 样本与执行约定

本轮证据与完整预期矩阵位于 tests/fixtures/rule-boundaries/。执行Agent只读README、scenarios与当前Skill；expected及维护者记录不提供给执行Agent。预期记录每项规则、证据位置、严重程度与禁止误报。局部通过仅表示该场景指定维度没有发现问题；完整审核仍遵守原有查重和必审覆盖关卡。

数量0、非法数值、内嵌流身份不匹配及混合结论由Runtime测试补充。程序测试只证明对应机械行为；Agent场景独立检验解释、适用性、建议及结论，二者不相互替代。

## 变更规则与正反覆盖

| 变更规则 | 合法、不触发问题 | 应形成问题或限制结论 | 实际结果 |
| --- | --- | --- | --- |
| common.optional.empty | O1 | O3（必填适用性待确认）；O2由已有optional.conflict识别 | 符合预期 |
| process.reference_flow.quantity_unit | Q1、Q3 | Q2、Q4；Runtime缺参考量 | 符合预期 |
| process.flow.semantic_match | F1、Runtime精确关联元数据 | F2、F3；Runtime缺元数据 | 符合预期 |
| process.flow.version_identity | Runtime精确/命名空间身份 | V3；Runtime错配、部分绑定与legacy | 符合预期 |
| process.source.traceability | S1 | S4；S3由已有document_availability识别 | 符合预期 |
| process.representativeness.consistency | R1 | R2、R3、R4 | 符合预期 |
| model.linked_process.audit | V1及既有模型回归 | V2、V4及既有错误版本/hash回归 | 符合预期 |

保留既有common.optional.conflict、process.source.field_conflict、process.source.document_availability的ID与判断条件。只读输入的missing不自动升级为提交缺失，已证实关键错误仍阻断。source.traceability默认严重程度由blocking改为manual_review；直接冲突依具体source规则，必要材料缺失依input_gap处理。数字文本的格式与科学适用性仍由证据决定。

## 实际Agent执行与独立复核

- [变更前原始输出](rule-boundaries-baseline-results.json)：17项，保留未经人工改写的Agent记录。
- [变更后原始输出](rule-boundaries-updated-results.json)：22项；7项局部通过、6项不通过、6项信息不足、3项需人工确认。执行者未读取expected和历史输出；指针、条目完整性和已注册规则均已校验。
- 独立行为复核逐项阅读全文证据和实际输出，22/22可接受；V3已使用具体版本规则。S1、S2、R2用具体规则且不重复报同根问题，V4以source.field_conflict定位数量冲突并保留model.linked_process.audit的独立缺口，均符合政策。
- R3 oracle修正已有独立政策依据；并未改写Agent答案以匹配预期。expected中的rule_ids表示允许的对应关系，不要求所有ID同时出现；严重程度、证据支持与同根去重须结合场景复核。
- 这些是合成证据上的局部能力观察，不声称总体误判率为零，也不证明完整平台审核、真实数据认证或线上部署。

## 复核中关闭的问题

规格复核实际复现：legacy内嵌名称为电力、引用自身描述为工业水且过程排除电力时，未绑定内嵌名称仍生成blocking。补充RED为5失败、2通过；新增共享受限证据视图，保护预检、独立guardrails和normalized claims。正例保留引用自身或matched内嵌电力带来的有效阻断；单位旁路的未绑定体积单位也被排除，交换自身及matched单位仍有效。规格复核独立运行相关10项回归通过，确认该问题关闭。

同时消除了过程审核方法把所有代表性未知统一指向人工确认的旧措辞，改由唯一规则和政策区分input_gap与manual_review。

其他分项TDD：claims零值3失败后修复；命名空间版本1失败后修复；缺失/非法参考量4失败、合法0/负值2通过后修复；已匹配参考属性缺单位1失败后修复。最终定向四文件150项通过。

## 最终验证

```bash
PYTHONPATH=src python3 -m tiangong_audit.cli check
PYTHONPATH=src python3 -m pytest -q
git diff --check
```

自检通过；全部535项测试通过（18.90秒），较基线新增59项；diff空白检查通过。环境没有python别名，使用python3执行相同模块。测试全部使用脱敏或临时材料。

独立规格复核通过；独立代码质量复核通过，后者另执行145项定向测试通过，未发现本轮重要回归或证据隔离旁路。本地整合前确认原工作区干净且仍在基线ed07322，已将实现提交b69494b快进整合到原工作区codex/haike。整合后再次自检通过、535项测试通过（22.51秒）、diff检查通过。


