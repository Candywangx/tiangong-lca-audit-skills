import json

import pytest

from tiangong_audit.contracts.evidence_ref import EvidenceReferenceError, resolve_evidence_ref


def test_plain_file_and_existing_json_pointer_values(tmp_path):
    path = tmp_path / '证据.json'
    path.write_text(json.dumps({'a/b': {'~': [0, False, None, '']}}))
    assert resolve_evidence_ref('证据.json', case_root=tmp_path).path == path
    for index in range(4):
        assert resolve_evidence_ref(f'证据.json#/a~1b/~0/{index}', case_root=tmp_path).path == path


@pytest.mark.parametrize('ref', ['', 'missing.md', 'a.json#/missing', 'a.json#/items/01', 'a.json#/items/-1', 'a.json#/bad~2key', 'a.json:p999', 'a.json:unknown', 'a.json\nother', 'bad\x00name'])
def test_invalid_refs_are_not_valid_evidence(tmp_path, ref):
    (tmp_path / 'a.json').write_text('{"items": [0]}')
    with pytest.raises(EvidenceReferenceError):
        resolve_evidence_ref(ref, case_root=tmp_path)


def test_page_and_global_block_locators(tmp_path):
    (tmp_path / 'source.md').write_text('# Page 1\n### Block 1 (text)\none\n## Page 3\n### Block 2\nthree\n')
    for ref in ('source.md:p1', 'source.md:p3', 'source.md:b2', 'source.md:p3:b2'):
        assert resolve_evidence_ref(ref, case_root=tmp_path).path.name == 'source.md'
    for ref in ('source.md:p2', 'source.md:p999', 'source.md:b3', 'source.md:p1:b2'):
        with pytest.raises(EvidenceReferenceError):
            resolve_evidence_ref(ref, case_root=tmp_path)


def test_plain_text_does_not_prove_page_number(tmp_path):
    (tmp_path / 'source.md').write_text('three paragraphs\n\nare not\n\nthree pages')
    with pytest.raises(EvidenceReferenceError, match='page'):
        resolve_evidence_ref('source.md:p3', case_root=tmp_path)


def test_parsing_json_uses_service_page_numbers_and_global_blocks(tmp_path):
    (tmp_path / 'result.json').write_text(json.dumps({'result': [{'text': 'a', 'page_number': 2}, {'text': 'b', 'page_number': 5}]}))
    assert resolve_evidence_ref('result.json:p5:b2', case_root=tmp_path).path.name == 'result.json'
    with pytest.raises(EvidenceReferenceError):
        resolve_evidence_ref('result.json:p2:b2', case_root=tmp_path)


def test_outside_paths_and_symlinks_are_rejected(tmp_path):
    root = tmp_path / 'case'
    root.mkdir()
    outside = tmp_path / 'private.txt'
    outside.write_text('outside')
    (root / 'escape.txt').symlink_to(outside)
    for ref in ('../private.txt', str(outside), 'escape.txt'):
        with pytest.raises(EvidenceReferenceError):
            resolve_evidence_ref(ref, case_root=root)


def test_directories_are_not_evidence_files(tmp_path):
    (tmp_path / 'directory').mkdir()
    with pytest.raises(EvidenceReferenceError):
        resolve_evidence_ref('directory', case_root=tmp_path)


def test_symlink_loop_is_a_validation_error(tmp_path):
    (tmp_path / 'loop').symlink_to(tmp_path / 'loop')
    with pytest.raises(EvidenceReferenceError):
        resolve_evidence_ref('loop', case_root=tmp_path)


def test_pdf_page_locator_checks_actual_page_count(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(tmp_path / 'source.pdf')
    assert resolve_evidence_ref('source.pdf:p1', case_root=tmp_path).page == 1
    with pytest.raises(EvidenceReferenceError, match='page'):
        resolve_evidence_ref('source.pdf:p2', case_root=tmp_path)


def test_invalid_parser_page_metadata_does_not_prove_a_page(tmp_path):
    (tmp_path / 'result.json').write_text(json.dumps({'result': [{'text': 'a', 'page_number': True}, {'text': 'b', 'page_number': '2'}]}))
    for ref in ('result.json:p1', 'result.json:p2', 'result.json:b1'):
        with pytest.raises(EvidenceReferenceError):
            resolve_evidence_ref(ref, case_root=tmp_path)
