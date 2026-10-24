"""Minimum model evidence checks; semantic importance remains an Agent judgment."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any

from tiangong_audit.contracts.agent_review import required_rule_ids
from tiangong_audit.contracts.evidence_ref import EvidenceReferenceError, resolve_evidence_ref

INDEX_PATH = 'agent-review/model-process-audits.json'
INDEX_SCHEMA_VERSION = 'tiangong-audit-model-process-audits-v1'
FULL_SCOPE = 'full-lca-semantic-review'


from .title_duplicate import dataset_payload

def dataset_snapshot_sha256(value: Any) -> str:
    """Hash semantic JSON content, independent of whitespace and row metadata."""
    return hashlib.sha256(json.dumps(dataset_payload(value if isinstance(value, dict) else {}), ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _positive_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def _read_object(ref: Any, case_root: Path) -> dict[str, Any]:
    location = resolve_evidence_ref(ref, case_root=case_root)
    if location.pointer is not None or location.page is not None or location.block is not None:
        raise ValueError('snapshot/report paths must identify complete JSON files')
    value = json.loads(location.path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value


def _refs_valid(refs: Any, case_root: Path) -> bool:
    if not isinstance(refs, list) or not refs:
        return False
    try:
        for ref in refs:
            resolve_evidence_ref(ref, case_root=case_root)
    except (EvidenceReferenceError, OSError, ValueError):
        return False
    return True


def _finding(rule_id: str, severity: str, location: str, evidence: str, suggestion: str) -> dict[str, Any]:
    return {'rule_id': rule_id, 'severity': severity, 'location': location, 'evidence': evidence,
        'judgment': ('该引用与完整实例表直接矛盾，模型结构不能按当前定义唯一解析。' if severity == 'blocking'
                     else '模型完整审核需要可核对的目标基准、结构和关联过程审核依据；语义关键性由 Agent 复核。'),
        'impact': '影响模型完整审核；完成证据复核后再确定结论。', 'suggestion': suggestion,
        'source': 'model-structure' if severity == 'blocking' else 'semantic-context',
        'platform_actionable': severity == 'blocking'}


def process_snapshot_identity(row: dict[str, Any]) -> tuple[str, str]:
    body = _dict(dataset_payload(row).get('processDataSet'))
    info = _dict(_dict(body.get('processInformation')).get('dataSetInformation'))
    publication = _dict(_dict(body.get('administrativeInformation')).get('publicationAndOwnership'))
    return (str(row.get('id') or info.get('common:UUID') or ''),
            str(row.get('version') or publication.get('common:dataSetVersion') or ''))


def _snapshot_identity(row: dict[str, Any], process_id: str, version: str) -> bool:
    body = _dict(dataset_payload(row).get('processDataSet'))
    info = _dict(_dict(body.get('processInformation')).get('dataSetInformation'))
    publication = _dict(_dict(body.get('administrativeInformation')).get('publicationAndOwnership'))
    ids = [value for value in (row.get('id'), info.get('common:UUID')) if value]
    versions = [value for value in (row.get('version'), publication.get('common:dataSetVersion')) if value]
    return bool(body and ids and versions and all(value == process_id for value in ids)
                and all(value == version for value in versions))


def _audit_report_errors(audit: dict[str, Any], entry: dict[str, Any], row: dict[str, Any], case_root: Path) -> list[str]:
    errors = []
    for key, expected in (('schema_version', 'tiangong-audit-semantic-review-v1'),
            ('dataset_type', 'process'), ('dataset_id', entry['process_id']), ('version', entry['version']),
            ('audit_scope', FULL_SCOPE)):
        if audit.get(key) != expected:
            errors.append(f'report {key} mismatch')
    completeness = _dict(audit.get('audit_completeness'))
    agent = _dict(audit.get('agent_review'))
    total = len(required_rule_ids('process'))
    if (completeness.get('complete') is not True or completeness.get('missing') != []
            or completeness.get('source_checks_valid') is not True
            or completeness.get('source_checks_present') is not True
            or agent.get('present') is not True or agent.get('valid') is not True
            or agent.get('required_total') != total or agent.get('required_covered') != total
            or agent.get('validation_error_count') != 0):
        errors.append('process semantic audit is incomplete or lacks required coverage')
    if (not isinstance(audit.get('review_task_id'), str) or not audit['review_task_id'].strip()
            or audit.get('conclusion') not in ('通过', '不通过', '信息不足', '需人工确认')
            or not isinstance(audit.get('findings'), list)
            or not isinstance(audit.get('source_consistency'), dict)
            or not isinstance(audit.get('rule_compliance'), dict)):
        errors.append('not a complete semantic-review report')
    expected_hash = dataset_snapshot_sha256(row)
    report_hash = audit.get('dataset_snapshot_sha256')
    if report_hash is None:
        # Old reports require their explicit, case-local semantic context. Never
        # infer a connection from file names or scan other case directories.
        try:
            context = _read_object(entry.get('context_path'), case_root)
            if (context.get('schema_version') != 'tiangong-audit-semantic-context-v1'
                    or context.get('review_id') != audit.get('review_task_id')
                    or context.get('dataset_id') != entry['process_id']
                    or context.get('version') != entry['version']
                    or dataset_snapshot_sha256(context.get('dataset_raw')) != expected_hash):
                errors.append('legacy report context identity or snapshot mismatch')
        except (OSError, ValueError):
            errors.append('legacy report needs its case-local semantic context snapshot')
    elif report_hash != expected_hash:
        errors.append('report snapshot hash mismatch')
    return errors


def _reference_quantity(row: dict[str, Any], entry: dict[str, Any], case_root: Path) -> tuple[bool, bool]:
    """Return (reference evidence available, numeric scaling interpretable)."""
    body = _dict(dataset_payload(row).get('processDataSet'))
    reference = _dict(_dict(body.get('processInformation')).get('quantitativeReference')).get('referenceToReferenceFlow')
    ids = reference if isinstance(reference, list) else [reference] if reference is not None else []
    exchanges = _items(_dict(body.get('exchanges')).get('exchange'))
    selected = [item for item in exchanges if isinstance(item, dict)
                and str(item.get('@dataSetInternalID')) in {str(value) for value in ids}]
    if len(ids) != 1 or len(selected) != 1:
        return False, False
    exchange = selected[0]
    amount = exchange.get('resultingAmount', exchange.get('meanAmount'))
    # Raw TIDAS exchanges generally do not carry a unit. Import an explicitly
    # reviewed flow/property/unit basis instead of inventing a required field.
    unit_basis = _dict(entry.get('reference_unit'))
    unit = unit_basis.get('unit')
    has_unit = isinstance(unit, str) and bool(unit.strip()) and _refs_valid(unit_basis.get('evidence_refs'), case_root)
    if not has_unit or amount is None:
        return False, False
    return True, _positive_number(amount)


def review_model(context: dict[str, Any], *, case_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    def add(rule: str, severity: str, location: str, evidence: str, suggestion: str) -> None:
        findings.append(_finding(rule, severity, location, evidence, suggestion))

    info = _dict(_dict(dataset_payload(context.get('dataset_raw')).get('lifeCycleModelDataSet')).get('lifeCycleModelInformation'))
    nodes = _items(_dict(_dict(info.get('technology')).get('processes')).get('processInstance'))
    reference = _dict(info.get('quantitativeReference')).get('referenceToReferenceProcess')
    if not _dict(_dict(info.get('dataSetInformation')).get('name')).get('baseName') or not nodes or not isinstance(reference, str) or not reference:
        add('model.core.input_coverage', 'input_gap', '模型目标 / 定量参考 / processInstance',
            '缺少可核查的模型名称、参考过程实例或完整实例表。', '提供实际模型目标、定量参考与实例表；仅名称和过程引用不能支持完整审核。')
    node_ids = [node.get('@dataSetInternalID') for node in nodes if isinstance(node, dict) and isinstance(node.get('@dataSetInternalID'), str)]
    duplicates = [node_id for node_id, count in Counter(node_ids).items() if count > 1]
    if duplicates:
        add('model.structure.connectivity', 'blocking', 'technology / processes / processInstance',
            f'完整实例表中实例ID重复：{duplicates}。', '为不同实例指定唯一内部ID，并更新参考和连接。')
    if isinstance(reference, str) and reference and nodes and reference not in node_ids:
        add('model.structure.connectivity', 'blocking', 'quantitativeReference / referenceToReferenceProcess',
            f'参考过程指向 {reference}，但完整实例表不存在该ID。', '将定量参考指向实际存在的过程实例。')
    valid_connection_seen = False
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('@dataSetInternalID'), str) or not node.get('@dataSetInternalID'):
            add('model.core.input_coverage', 'input_gap', 'processInstance', '实例缺少可识别的内部ID。', '提供完整过程实例。')
            continue
        node_id = node['@dataSetInternalID']
        if node.get('@multiplicationFactor') in (None, ''):
            add('model.core.input_coverage', 'input_gap', f'processInstance / {node_id}', '实例未提供multiplicationFactor，目标量基准无法核对。', '提供实例缩放系数或可复核的参数依据。')
        elif not _positive_number(node.get('@multiplicationFactor')) or node.get('parameters') or node.get('scalingFactors'):
            add('model.goal.consistency', 'manual_review', f'processInstance / {node_id} / multiplicationFactor',
                f'实例缩放为 {node.get("@multiplicationFactor")!r}，或含额外参数/缩放定义，尚不能直接解释目标量。', '核查参数、零值或负值缩放的含义与目标量关系，并保留人工确认。')
        connections = node.get('connections')
        outputs = _dict(connections).get('outputExchange')
        if ((connections is not None and not isinstance(connections, dict))
                or (outputs is not None and not isinstance(outputs, (dict, list)))):
            add('model.core.input_coverage', 'input_gap', f'processInstance / {node_id} / connections', '连接容器不是可读取的TIDAS结构。', '提供object或array形式的输出交换与下游实例。')
        for output in _items(outputs):
            if not isinstance(output, dict):
                add('model.core.input_coverage', 'input_gap', f'processInstance / {node_id} / connections', '连接记录不完整。', '提供输出交换和下游实例ID。')
                continue
            downstream = _items(output.get('downstreamProcess'))
            if not output.get('@flowUUID') or not downstream:
                add('model.core.input_coverage', 'input_gap', f'processInstance / {node_id} / connections', '显式连接缺少输出流或下游记录。', '补充连接的输出流和下游实例引用。')
            for target in downstream:
                target_id = _dict(target).get('@id')
                if not isinstance(target_id, str) or not target_id or not _dict(target).get('@flowUUID'):
                    add('model.core.input_coverage', 'input_gap', f'processInstance / {node_id} / connections', '显式下游记录缺少实例ID或输入流引用。', '补充下游实例ID和流引用。')
                elif target_id not in node_ids:
                    add('model.structure.connectivity', 'blocking', f'processInstance / {node_id} / downstreamProcess', f'下游实例 {target_id} 不存在于完整实例表。', '修正连接引用或补齐对应实例。')
                else:
                    valid_connection_seen = True

    index: dict[str, Any] = {}
    try:
        index = _read_object(INDEX_PATH, case_root)
        if index.get('schema_version') != INDEX_SCHEMA_VERSION or index.get('audit_scope') not in (FULL_SCOPE, 'partial') or not isinstance(index.get('process_audits'), list):
            raise ValueError('invalid model process audit index')
    except (OSError, ValueError) as error:
        add('model.linked_process.audit', 'input_gap', INDEX_PATH, f'未取得有效关联过程审核索引：{error}', '提供绑定过程ID、版本、快照与语义审核报告的索引。')
    scope = index.get('audit_scope') if index.get('audit_scope') in (FULL_SCOPE, 'partial') else FULL_SCOPE
    if scope == 'partial':
        add('model.core.input_coverage', 'manual_review', INDEX_PATH, '本轮明确为局部模型审核，不能导出完整模型通过。', '保留局部审核范围；完成其余目标、过程和质量检查后再申请完整审核。')
    roles = _items(index.get('node_roles'))
    entries = _items(index.get('process_audits'))
    required_node_ids: list[str] = []
    audited: set[tuple[str, str]] = set()
    required: set[tuple[str, str]] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get('@dataSetInternalID')
        role = next((item for item in roles if isinstance(item, dict) and item.get('instance_id') == node_id), {})
        exempt = (node_id != reference and role.get('is_key') is False and isinstance(role.get('reason'), str)
                  and bool(role['reason'].strip()) and _refs_valid(role.get('evidence_refs'), case_root))
        ref = _dict(node.get('referenceToProcess'))
        process_id, version = ref.get('@refObjectId'), ref.get('@version')
        location = f'模型实例 {node_id} / 过程 {process_id}@{version}'
        if not isinstance(process_id, str) or not process_id or not isinstance(version, str) or not version:
            add('model.linked_process.audit', 'input_gap', location, '关联过程引用缺少ID或版本。', '补充过程引用的完整ID和版本。')
            continue
        if not exempt and isinstance(node_id, str):
            required_node_ids.append(node_id)
        key = (process_id, version)
        if not exempt:
            required.add(key)
        matches = [item for item in entries if isinstance(item, dict) and item.get('process_id') == process_id and item.get('version') == version]
        try:
            if len(matches) != 1:
                raise ValueError('each required process needs one unambiguous audit entry')
            entry = matches[0]
            row = _read_object(entry.get('snapshot_path'), case_root)
            if not _snapshot_identity(row, process_id, version):
                raise ValueError('process snapshot identity/version mismatch')
            snapshot_hash = dataset_snapshot_sha256(row)
            if entry.get('snapshot_sha256') != snapshot_hash:
                raise ValueError('process snapshot hash mismatch')
            current = [item for item in _items(_dict(context.get('model_evidence')).get('linked_processes'))
                       if _dict(item).get('id') == process_id and _dict(item).get('version') == version]
            if not current:
                raise ValueError('current materialized process snapshot is missing')
            current_hashes = {dataset_snapshot_sha256(_read_object(item.get('path'), case_root)) for item in current}
            if current_hashes != {snapshot_hash}:
                raise ValueError('audit snapshot does not match the current materialized process')
            if exempt:
                available, numeric = _reference_quantity(row, entry, case_root)
                if not available:
                    raise ValueError('nonkey process still needs object/reference-flow and unit evidence')
                if not numeric:
                    add('model.linked_process.role_match', 'manual_review', location, '非关键过程基准量尚不能解释。', '核查该非关键过程的基准流、缩放和连接角色。')
                continue
            audit = _read_object(entry.get('report_path'), case_root)
            errors = _audit_report_errors(audit, entry, row, case_root)
            if errors:
                raise ValueError('; '.join(errors))
            audited.add(key)
            if node_id == reference:
                available, numeric = _reference_quantity(row, entry, case_root)
                if not available:
                    add('model.core.input_coverage', 'input_gap', location, '参考过程缺少可解释的定量参考、基准交换数量或有证据的单位。', '提供关联过程的定量参考、交换数量，以及流/属性/单位依据的引用。')
                elif not numeric:
                    add('model.goal.consistency', 'manual_review', location, '基准交换数量无法按固定正数解释。', '核查基准交换数量和模型缩放关系。')
            if any(_dict(item).get('severity') in ('blocking', 'manual_review', 'input_gap') for item in audit.get('findings', [])):
                add('model.linked_process.audit', 'manual_review', location, '关联过程已审报告存在可能影响模型的发现，影响尚需逐项解释。', '由 Agent 说明过程问题对模型角色、数量和边界的影响；有充分证据时另给模型级判断。')
        except (OSError, ValueError) as error:
            add('model.linked_process.audit', 'input_gap', location, f'关联过程审核证据不完整：{error}', '提供与当前ID、版本和快照hash绑定的完整过程语义审核报告。')

    if len(required_node_ids) > 1 and not valid_connection_seen:
        add('model.core.input_coverage', 'input_gap', 'technology / processes / connections',
            '多个需审实例没有任何连接定义，尚未取得完整模型结构依据。', '提供实例连接关系；有意排除的非关键实例须由 Agent 附证据说明角色。')
    for precheck in _items(_dict(context.get('model_evidence')).get('linked_prechecks')):
        if _dict(_dict(precheck).get('summary')).get('blocking'):
            add('model.linked_process.audit', 'manual_review', str(_dict(precheck).get('path') or '关联过程预检'),
                '关联过程预检报告阻断项，其模型影响尚未证实。', '由 Agent 核查该问题是否影响模型目标、连接或结果，不以过程预检自动驳回模型。')
    complete = scope == FULL_SCOPE and bool(nodes) and not any(item['severity'] in ('blocking', 'input_gap', 'manual_review') for item in findings)
    return findings, {'complete': complete, 'audit_scope': scope, 'required_process_count': len(required), 'audited_process_count': len(audited)}
