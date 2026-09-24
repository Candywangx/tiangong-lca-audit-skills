"""Exercise the distributed client over HTTP without uploading real sources."""

import hashlib
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parents[1] / "skill/document-granular-decompose/scripts"
)
sys.path.insert(0, str(SCRIPTS))


def client_module():
    spec = importlib.util.spec_from_file_location(
        "decompose_cli", SCRIPTS / "mineru_fulltext_extract.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def business():
    return {
        "result": [
            {"text": "Inventory", "page_number": 2, "type": "title"},
            {"text": "<table><tr><td>10 kg</td></tr></table>", "page_number": 2},
            {"text": "Approximately 7 kg", "page_number": 3, "type": "image"},
            {"text": "Supplementary Table S8", "page_number": 3, "type": None},
        ],
        "txt": "Native DOCX text may differ",
    }


def schema():
    paths = {}
    for path in [
        "/mineru",
        "/mineru_with_images",
        "/mineru/task",
        "/mineru_with_images/task",
        "/two_stage/task",
    ]:
        fields = {
            "file": {"type": "string", "format": "binary"},
            "tier": {"enum": ["flash", "basic", "standard", "advanced"]},
        }
        query = ["chunk_type", "return_txt"]
        if path == "/two_stage/task":
            fields.update({key: {"type": "boolean"} for key in query})
            query = []
        if "images" in path or "two_stage" in path:
            fields.update(
                {key: {"type": "string"} for key in ["provider", "model", "prompt"]}
            )
        paths[path] = {
            "post": {
                "parameters": [
                    {"name": key, "in": "query", "schema": {"type": "boolean"}}
                    for key in query
                ],
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {"type": "object", "properties": fields}
                        }
                    }
                },
            }
        }
        if path.endswith("/task"):
            paths[path + "/{task_id}"] = {"get": {}}
    return {"openapi": "3.1.0", "paths": paths}


@pytest.fixture
def service():
    state = {
        "requests": [],
        "post": {"task_id": "task-1", "state": "PENDING"},
        "poll": {"task_id": "task-1", "state": "SUCCESS", "result": business()},
        "poll_status": 200,
        "schema": schema(),
        "sync": business(),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, payload, status=200):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if state.get("slow_poll") and "/task/" in self.path:
                import time

                try:
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.wfile.write(data)

        def truncated(self):
            self.send_response(200)
            self.send_header("Content-Length", "9999")
            self.end_headers()
            self.wfile.write(b"{")
            self.close_connection = True

        def slow_chunked(self):
            import time

            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"1\r\n{\r\n0\r\nX-Trailer: ")
            try:
                for _ in range(60):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.01)
                self.wfile.write(b"\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            state["requests"].append(("GET", self.path, b""))
            if self.path.endswith("/openapi.json"):
                if state.get("on_schema"):
                    state["on_schema"]()
                self.reply(state["schema"])
            elif state.get("poll_truncated"):
                self.truncated()
            elif state.get("slow_chunked"):
                self.slow_chunked()
            else:
                self.reply(state["poll"], state["poll_status"])

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            assert self.headers["Authorization"] == "Bearer test-secret"
            state["requests"].append(("POST", self.path, body))
            if state.get("post_truncated"):
                self.truncated()
                return
            self.reply(state["post"] if "/task" in self.path else state["sync"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/prefix"
    yield state
    server.shutdown()
    thread.join()
    server.server_close()


def run(monkeypatch, service, tmp_path, *args):
    monkeypatch.setenv("UNSTRUCTURED_API_BASE_URL", service["url"])
    monkeypatch.setenv("UNSTRUCTURED_AUTH_TOKEN", "test-secret")
    monkeypatch.delenv("UNSTRUCTURED_PROVIDER", raising=False)
    monkeypatch.delenv("UNSTRUCTURED_MODEL", raising=False)
    file = tmp_path / "source.pdf"
    if not file.exists():
        file.write_bytes(b"%PDF synthetic test")
    monkeypatch.setattr(sys, "argv", ["extract", "--file", str(file), *args])
    return client_module().main()


def test_sync_saves_page_evidence_without_losing_null_types(
    monkeypatch, service, tmp_path
):
    output = tmp_path / "parsed"
    assert run(monkeypatch, service, tmp_path, "--output-dir", str(output)) == 0
    parsed = json.loads((output / "result.json").read_text())
    assert parsed == business()
    text = (output / "extracted.md").read_text()
    assert "Page 2" in text and "Page 3" in text
    assert "10 kg" in text and "Supplementary Table S8" in text
    assert "model-generated" in text and text.index("10 kg") < text.index(
        "Approximately"
    )
    assert (output / "fulltext.txt").read_text() == business()["txt"]
    post = next(req for req in service["requests"] if req[0] == "POST")
    assert post[1] == "/prefix/mineru?chunk_type=true&return_txt=true"
    assert b'name="tier"' in post[2] and b"advanced" in post[2]
    assert b'name="provider"' not in post[2]
    record = json.loads((output / "request.json").read_text())
    assert record["state"] == "SUCCESS"
    assert (
        record["result_sha256"]
        == hashlib.sha256((output / "result.json").read_bytes()).hexdigest()
    )
    assert "test-secret" not in (output / "request.json").read_text()


@pytest.mark.parametrize(
    "mode,endpoint",
    [
        ("parse", "mineru/task"),
        ("images", "mineru_with_images/task"),
        ("two-stage", "two_stage/task"),
    ],
)
def test_async_modes_preserve_parameter_locations_and_resume(
    monkeypatch, service, tmp_path, mode, endpoint
):
    output = tmp_path / "parsed"
    args = ["--mode", mode, "--async", "--output-dir", str(output)]
    assert run(monkeypatch, service, tmp_path, *args) == 0
    posts = [req for req in service["requests"] if req[0] == "POST"]
    assert len(posts) == 1
    if mode == "two-stage":
        assert posts[0][1] == "/prefix/" + endpoint
        assert b'name="chunk_type"' in posts[0][2]
    else:
        assert posts[0][1] == "/prefix/" + endpoint + "?chunk_type=true&return_txt=true"
        assert b'name="chunk_type"' not in posts[0][2]
    assert run(monkeypatch, service, tmp_path, *args) == 0
    assert sum(req[0] == "POST" for req in service["requests"]) == 1
    (output / "result.json").unlink()
    assert run(monkeypatch, service, tmp_path, *args) == 0
    assert (output / "result.json").exists()
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_timeout_then_resume_without_input_or_reupload(monkeypatch, service, tmp_path):
    output = tmp_path / "parsed"
    service["poll"] = {"task_id": "task-1", "state": "PENDING"}
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--async",
            "--output-dir",
            str(output),
            "--poll-timeout",
            "0.01",
            "--poll-interval",
            "0.001",
        )
        == 1
    )
    record = json.loads((output / "request.json").read_text())
    assert record["task_id"] == "task-1"
    (tmp_path / "source.pdf").unlink()
    service["poll"] = {"task_id": "task-1", "state": "SUCCESS", "result": business()}
    monkeypatch.setattr(
        sys, "argv", ["extract", "--resume-only", "--output-dir", str(output)]
    )
    assert client_module().main() == 0
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_ambiguous_submission_never_reposts(monkeypatch, service, tmp_path):
    output = tmp_path / "parsed"
    service["post"] = {"missing": "task-id"}
    args = ["--async", "--output-dir", str(output)]
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert json.loads((output / "request.json").read_text())["state"] == "SUBMITTING"
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


@pytest.mark.parametrize("status", [200, 500])
def test_terminal_task_failure_never_reposts(monkeypatch, service, tmp_path, status):
    service["poll_status"] = status
    service["poll"] = {"task_id": "task-1", "state": "FAILURE", "error": "parse failed"}
    args = ["--async", "--output-dir", str(tmp_path / "parsed")]
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"result": []},
        {"txt": "looks okay"},
        {"result": [{"text": "x", "page_number": 0}]},
        {"result": [{"text": "x", "page_number": True}]},
    ],
)
def test_invalid_results_do_not_become_evidence(
    monkeypatch, service, tmp_path, payload
):
    service["sync"] = payload
    output = tmp_path / "parsed"
    assert run(monkeypatch, service, tmp_path, "--output-dir", str(output)) == 1
    assert not (output / "extracted.md").exists()


def test_schema_mismatch_stops_before_upload(monkeypatch, service, tmp_path):
    service["schema"]["paths"]["/mineru"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["properties"].pop("tier")
    assert (
        run(monkeypatch, service, tmp_path, "--output-dir", str(tmp_path / "parsed"))
        == 1
    )
    assert not any(req[0] == "POST" for req in service["requests"])


def test_changed_file_rejects_existing_task(monkeypatch, service, tmp_path):
    args = ["--async", "--output-dir", str(tmp_path / "parsed")]
    assert run(monkeypatch, service, tmp_path, *args) == 0
    (tmp_path / "source.pdf").write_bytes(b"changed")
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_supported_formats_match_service():
    module = client_module()
    module.validate_file_type(Path("source.tif"))
    for extension in ["gif", "jp2", "txt", "md"]:
        with pytest.raises(ValueError):
            module.validate_file_type(Path("source." + extension))


def test_temporary_query_error_body_does_not_discard_task(
    monkeypatch, service, tmp_path
):
    output = tmp_path / "parsed"
    service["poll_status"] = 503
    service["poll"] = {"detail": "backend warming up"}
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--async",
            "--output-dir",
            str(output),
            "--poll-timeout",
            "0.08",
            "--poll-interval",
            "0.005",
        )
        == 1
    )
    assert (
        sum(req[0] == "GET" and "/task/" in req[1] for req in service["requests"]) > 1
    )
    service["poll_status"] = 200
    service["poll"] = {"task_id": "task-1", "state": "SUCCESS", "result": business()}
    assert (
        run(monkeypatch, service, tmp_path, "--async", "--output-dir", str(output)) == 0
    )
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_image_options_and_legacy_endpoint(monkeypatch, service, tmp_path):
    service["url"] += "/mineru_with_images"
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--provider",
            "vllm",
            "--model",
            "vision",
            "--prompt",
            "Read units exactly",
            "--output",
            str(tmp_path / "plain.txt"),
        )
        == 0
    )
    post = next(req for req in service["requests"] if req[0] == "POST")
    assert post[1] == "/prefix/mineru_with_images?chunk_type=true&return_txt=true"
    for value in [b'name="provider"', b"vllm", b"vision", b"Read units exactly"]:
        assert value in post[2]
    assert (tmp_path / "plain.txt").read_text() == business()["txt"]


def test_openapi_references_and_rejected_model_enum(monkeypatch, service, tmp_path):
    operation = service["schema"]["paths"]["/two_stage/task"]["post"]
    body = operation["requestBody"]["content"]["multipart/form-data"]
    definition = body["schema"]
    definition["properties"]["model"] = {
        "anyOf": [{"$ref": "#/components/schemas/VisionModel"}, {"type": "null"}]
    }
    service["schema"]["components"] = {
        "schemas": {"Upload": definition, "VisionModel": {"enum": ["configured-model"]}}
    }
    body["schema"] = {"$ref": "#/components/schemas/Upload"}
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--mode",
            "two-stage",
            "--model",
            "wrong-model",
            "--output-dir",
            str(tmp_path / "parsed"),
        )
        == 1
    )
    assert not any(req[0] == "POST" for req in service["requests"])
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--mode",
            "two-stage",
            "--model",
            "configured-model",
            "--output-dir",
            str(tmp_path / "parsed"),
        )
        == 0
    )


def test_refuses_overwriting_source_and_bundle_files(monkeypatch, service, tmp_path):
    assert (
        run(monkeypatch, service, tmp_path, "--output", str(tmp_path / "source.pdf"))
        == 1
    )
    assert run(monkeypatch, service, tmp_path, "--output-dir", str(tmp_path)) == 1
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--output-dir",
            str(tmp_path / "parsed"),
            "--output",
            str(tmp_path / "parsed/result.json"),
        )
        == 1
    )
    assert not any(req[0] == "POST" for req in service["requests"])


def test_changed_request_and_other_task_results_rejected(
    monkeypatch, service, tmp_path
):
    output = tmp_path / "parsed"
    service["poll"]["task_id"] = "different-task"
    args = ["--async", "--output-dir", str(output)]
    assert run(monkeypatch, service, tmp_path, *args) == 1
    assert not (output / "result.json").exists()
    assert run(monkeypatch, service, tmp_path, *args, "--tier", "basic") == 1
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_two_clients_cannot_use_same_output(monkeypatch, service, tmp_path):
    import fcntl

    output = tmp_path / "parsed"
    output.mkdir()
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(monkeypatch, service, tmp_path, "--output-dir", str(output)) == 1
    assert not service["requests"]


def test_distributed_skill_runs_without_project_install(monkeypatch, service, tmp_path):
    import os
    import shutil
    import subprocess

    copied = tmp_path / "distributed-skill"
    shutil.copytree(
        SCRIPTS.parent, copied, ignore=shutil.ignore_patterns("__pycache__")
    )
    source = tmp_path / "sample.docx"
    source.write_bytes(b"synthetic Office upload")
    output = tmp_path / "standalone-result"
    env = dict(
        os.environ,
        UNSTRUCTURED_API_BASE_URL=service["url"],
        UNSTRUCTURED_AUTH_TOKEN="test-secret",
    )
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(copied / "scripts/mineru_fulltext_extract.py"),
            "--file",
            str(source),
            "--mode",
            "images",
            "--output-dir",
            str(output),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads((output / "result.json").read_text()) == business()
    assert (output / "fulltext.txt").read_text() != (
        output / "extracted.md"
    ).read_text()


@pytest.mark.parametrize("phase", ["post", "poll"])
def test_truncated_http_body_is_recoverable_without_repost(
    monkeypatch, service, tmp_path, phase
):
    output = tmp_path / "parsed"
    service[phase + "_truncated"] = True
    args = [
        "--async",
        "--output-dir",
        str(output),
        "--poll-timeout",
        "0.08",
        "--poll-interval",
        "0.005",
    ]
    assert run(monkeypatch, service, tmp_path, *args) == 1
    if phase == "poll":
        assert (
            sum(req[0] == "GET" and "/task/" in req[1] for req in service["requests"])
            > 1
        )
        service["poll_truncated"] = False
        assert run(monkeypatch, service, tmp_path, *args) == 0
    else:
        assert run(monkeypatch, service, tmp_path, *args) == 1
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_uploaded_bytes_match_provenance_when_source_is_replaced(
    monkeypatch, service, tmp_path
):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF version A")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    service["on_schema"] = lambda: source.write_bytes(b"%PDF version B")
    output = tmp_path / "parsed"
    assert run(monkeypatch, service, tmp_path, "--output-dir", str(output)) == 0
    post = next(req for req in service["requests"] if req[0] == "POST")
    assert b"%PDF version A" in post[2] and b"%PDF version B" not in post[2]
    assert (
        json.loads((output / "request.json").read_text())["identity"]["sha256"]
        == expected
    )


def test_slow_response_respects_poll_budget(monkeypatch, service, tmp_path):
    import time

    service["slow_poll"] = True
    service["poll"] = {"task_id": "task-1", "state": "PENDING"}
    output = tmp_path / "parsed"
    start = time.monotonic()
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--async",
            "--output-dir",
            str(output),
            "--poll-timeout",
            "0.07",
            "--poll-interval",
            "0.005",
        )
        == 1
    )
    assert time.monotonic() - start < 0.4
    assert json.loads((output / "request.json").read_text())["task_id"] == "task-1"
    assert sum(req[0] == "POST" for req in service["requests"]) == 1


def test_http_parser_bundle_attaches_to_audit_case(monkeypatch, service, tmp_path):
    from tiangong_audit.case_store import CaseStore
    from tiangong_audit.workflows import attach_extraction

    output = tmp_path / "parsed"
    assert run(monkeypatch, service, tmp_path, "--output-dir", str(output)) == 0
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-parser", dataset_type="process", batch_id="parser-test"
    )
    source_dir = tmp_path / "cases" / manifest.case_dir / "sources/source-001"
    source_dir.mkdir(parents=True)
    (source_dir / "extracted.md").write_text("basic text")
    (source_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "tiangong-audit-source-v1",
                "ref": {"source_id": "source-1"},
                "status": "extracted",
                "sha256": hashlib.sha256(
                    (tmp_path / "source.pdf").read_bytes()
                ).hexdigest(),
                "extracted_text_path": "extracted.md",
            }
        )
    )
    attach_extraction(
        "review-parser",
        root=tmp_path,
        source_dir_name="source-001",
        extracted_text=output / "extracted.md",
        extraction_dir=output,
        case_store=store,
        batch_id="parser-test",
    )
    attached = json.loads((source_dir / "manifest.json").read_text())
    assert set(attached["extraction_bundle"]["files"]) == {
        "result.json",
        "extracted.md",
        "fulltext.txt",
        "request.json",
        "openapi.json",
    }
    assert (source_dir / "parsing/result.json").read_bytes() == (
        output / "result.json"
    ).read_bytes()
    assert (source_dir / "extracted.md").read_bytes() == (
        output / "extracted.md"
    ).read_bytes()
    assert (source_dir / "extracted.basic.md").read_text() == "basic text"
    assert any(
        item["reference"] == "Supplementary Table S8"
        for item in attached["related_artifact_requirements"]
    )


def test_slow_chunked_trailer_respects_poll_budget(monkeypatch, service, tmp_path):
    import time

    service["slow_chunked"] = True
    output = tmp_path / "parsed"
    start = time.monotonic()
    assert (
        run(
            monkeypatch,
            service,
            tmp_path,
            "--async",
            "--output-dir",
            str(output),
            "--poll-timeout",
            "0.07",
            "--poll-interval",
            "0.005",
        )
        == 1
    )
    assert time.monotonic() - start < 0.4
    assert json.loads((output / "request.json").read_text())["task_id"] == "task-1"
    assert sum(req[0] == "POST" for req in service["requests"]) == 1
