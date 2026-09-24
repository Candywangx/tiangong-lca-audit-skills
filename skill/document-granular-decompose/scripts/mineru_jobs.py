"""Durable single-document lifecycle. Resuming means GET, never blind POST retries."""

from __future__ import annotations

import fcntl
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode

from mineru_client import Client, inspect_schema
from mineru_results import (
    cached_result,
    file_digest,
    save_result,
    validate_result,
    write_json,
)


@contextmanager
def output_lock(directory: Path | None):
    if directory is None:
        yield
        return
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Output directory is already in use by another client."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_record(directory: Path) -> dict | None:
    path = directory / "request.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("identity"), dict):
        raise TypeError("Invalid saved request record; preserve it for investigation.")
    return payload


def poll(
    client: Client, directory: Path, record: dict, *, budget: float, interval: float
) -> dict:
    task_id = record["task_id"]
    url = record["identity"]["endpoint"] + "/" + quote(task_id, safe="")
    deadline = time.monotonic() + budget
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "Stopped waiting; task ID is saved. Resume using the same output directory."
            )
        try:
            status, payload = client.call(
                "GET", url, timeout=min(client.timeout, remaining), deadline=deadline
            )
        except RuntimeError:
            status, payload = 503, None
        if status in {401, 403}:
            raise RuntimeError(
                f"HTTP {status}; fix authentication and resume the saved task."
            )
        state = payload.get("state") if isinstance(payload, dict) else None
        if (state is not None or 200 <= status < 300) and (
            not isinstance(payload, dict) or payload.get("task_id") != task_id
        ):
            raise ValueError("Task response does not match the saved task ID.")
        if state in {"FAILURE", "REVOKED"}:
            record["state"] = state
            # Do not persist arbitrary service error strings that could echo credentials.
            write_json(directory / "request.json", record)
            raise RuntimeError(
                f"Service task ended in {state}; inspect service logs before starting a new request."
            )
        if status not in {429, 500, 502, 503, 504}:
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status} querying the saved task.")
            if state == "SUCCESS":
                result = validate_result(payload.get("result"))
                save_result(directory, result, record)
                return result
            if state not in {"PENDING", "STARTED", "RETRY", "RECEIVED"}:
                raise ValueError(
                    "Unexpected task state; preserve task ID and inspect service."
                )
        time.sleep(min(interval, max(0, deadline - time.monotonic())))


def resume(
    client: Client, directory: Path, record: dict, *, budget: float, interval: float
) -> dict:
    schema = directory / "openapi.json"
    if not schema.is_file() or file_digest(schema) != record.get("schema_sha256"):
        raise ValueError(
            "Saved OpenAPI evidence is missing or changed; preserve this task record."
        )
    cached = cached_result(directory, record)
    if cached is not None:
        # Also restore missing/changed rendered outputs from the verified raw result.
        save_result(directory, cached, record)
        return cached
    if record.get("state") in {"FAILURE", "REVOKED"}:
        raise RuntimeError(
            "Saved task failed; no automatic resubmission. Investigate before using a new directory."
        )
    if record.get("state") == "SUBMITTING" or not record.get("task_id"):
        raise RuntimeError(
            "Submission outcome is unknown or synchronous result is unavailable. Do not re-upload; investigate service logs."
        )
    if not isinstance(record["task_id"], str):
        raise TypeError("Invalid saved task ID.")
    return poll(client, directory, record, budget=budget, interval=interval)


def execute(
    client: Client,
    *,
    root: str,
    identity: dict,
    file: Path,
    directory: Path | None,
    budget: float,
    interval: float,
) -> dict:
    record = read_record(directory) if directory else None
    if record is not None:
        if record["identity"] != identity:
            raise ValueError("Input or request changed; use a new output directory.")
        return resume(client, directory, record, budget=budget, interval=interval)
    if directory and any(
        p.name not in {".lock", "openapi.json"} for p in directory.iterdir()
    ):
        raise ValueError(
            "Output directory contains untracked artifacts; use a new directory."
        )
    # The original pathname can change during preflight/upload. Send a private
    # snapshot whose digest matches the recorded source identity.
    with TemporaryDirectory(prefix="mineru-upload-") as temporary:
        snapshot = Path(temporary) / file.name
        shutil.copyfile(file, snapshot)
        if file_digest(snapshot) != identity["sha256"]:
            raise ValueError(
                "Input changed while preparing upload; no request was submitted."
            )
        snapshot.chmod(0o400)
        schema = inspect_schema(
            client,
            root,
            identity["endpoint"],
            identity["fields"],
            identity["query"],
            identity["asynchronous"],
        )
        record = {"identity": identity, "state": "SUBMITTING"}
        if directory:
            write_json(directory / "openapi.json", schema)
            record["schema_sha256"] = file_digest(directory / "openapi.json")
            write_json(directory / "request.json", record)
        query = urlencode(identity["query"])
        url = identity["endpoint"] + ("?" + query if query else "")
        payload = client.require("POST", url, fields=identity["fields"], file=snapshot)
    if identity["asynchronous"]:
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(
                "Submission response lacks a task ID; outcome unknown, do not re-upload."
            )
        record.update(task_id=task_id, state="SUBMITTED")
        write_json(directory / "request.json", record)
        return poll(client, directory, record, budget=budget, interval=interval)
    payload = validate_result(payload)
    if directory:
        save_result(directory, payload, record)
    return payload
