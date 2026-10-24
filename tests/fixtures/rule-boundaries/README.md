# 五类规则边界 Agent 验收

全部为脱敏合成材料，仅用于指定维度的局部审核，不代表真实数据或完整数据集认证。每个场景相互独立，证据以 scenarios.json 对应对象为准。禁止访问平台或写入平台；无需生成案件、执行完整审核关卡或虚构未提供的其他维度。

阅读现有 Skill 的 audit-policy、input-contract、相关 process/model 方法及规则，再逐例判断。不要把页面字段或平台标记当作科学真实性证明。输出 JSON 对象含 scope=targeted-rule-boundaries 和 results 数组，每项含 case_id、verdict(pass/fail/cannot_judge)、conclusion(局部通过/不通过/信息不足/需人工确认)、rule_ids、findings。每条 finding 含 rule_id、severity、location、evidence、evidence_refs、judgment、suggestion；引用使用 scenarios.json#/cases/N/evidence/M。没有问题时 findings=[]，但另写 rationale 和 evidence_refs 说明依据。依据不足不能填写虚构的事实。若同时存在有效阻断与缺口，保留两者并聚合结论。


维护者重放时，将本目录README与scenarios以及当前Skill交给无历史上下文的独立Agent，不提供expected或历史输出。保存原始JSON后逐例检查事实支持、具体规则、严重程度、建议与局部结论，并保留独立复核记录。expected的rule_ids为该问题允许的对应规则，不要求重复列出所有ID或重复报告同根发现；V4必须同时保留数量冲突和独立版本缺口。自动检查定位与字段非空不能替代语义复核。
