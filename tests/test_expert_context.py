from tiangong_audit.experts.context import dataset_evidence


def test_ambiguous_title_keeps_reference_product_and_flow_pointer():
    payload = {'processDataSet': {
        'processInformation': {'dataSetInformation': {'name': {'baseName': '板材'}},
                               'quantitativeReference': {'referenceToReferenceFlow': '5'}},
        'exchanges': {'exchange': [
            {'@dataSetInternalID': '1', 'exchangeDirection': 'Input',
             'referenceToFlow': {'common:shortDescription': '电力'}},
            {'@dataSetInternalID': '5', 'exchangeDirection': 'Output',
             'referenceToFlow': {'common:shortDescription': '测试纤维板产品'}, 'meanAmount': 1}]}}}
    evidence = dataset_evidence(payload, snapshot_ref='snapshots/test.json')
    rows = {r['ref']: r['text'] for r in evidence}
    assert rows['snapshots/test.json#/processDataSet/processInformation/quantitativeReference/referenceToReferenceFlow'] == '5'
    assert rows['snapshots/test.json#/processDataSet/exchanges/exchange/1/@dataSetInternalID'] == '5'
    assert rows['snapshots/test.json#/processDataSet/exchanges/exchange/1/referenceToFlow/common:shortDescription'] == '测试纤维板产品'
    assert rows['snapshots/test.json#/processDataSet/exchanges/exchange/1/exchangeDirection'] == 'Output'


def test_evidence_does_not_invent_a_reference_flow_or_include_contacts():
    payload = {'processDataSet': {'processInformation': {'dataSetInformation': {'name': '未明确产品'}},
                                 'administrativeInformation': {'email': 'private@example.test'}}}
    evidence = dataset_evidence(payload, snapshot_ref='snapshot.json')
    assert not any('referenceToReferenceFlow' in r['ref'] for r in evidence)
    assert not any('private@example.test' in r['text'] for r in evidence)


def test_model_and_linked_process_are_distinct_evidence_sources():
    model = {'lifeCycleModelDataSet': {'lifeCycleModelInformation': {'technology': {'processes': {
        'processInstance': [{'referenceToProcess': {'@refObjectId': 'process-1'}}]}}}}}
    rows = dataset_evidence(model, snapshot_ref='model.json')
    assert rows == [{'ref':'model.json#/lifeCycleModelDataSet/lifeCycleModelInformation/technology/processes/processInstance/0/referenceToProcess/@refObjectId','text':'process-1'}]
