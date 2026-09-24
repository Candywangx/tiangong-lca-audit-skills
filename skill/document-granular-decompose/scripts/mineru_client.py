"""MinerU HTTP contract; no GPU, service package, or third-party client required."""

from __future__ import annotations

import json
import socket
import ssl
import time
import uuid
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from threading import Timer
from urllib import error, parse, request

OFFICE_FILE_TYPES = {
    ".doc",
    ".docx",
    ".docm",
    ".dot",
    ".dotx",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".pot",
    ".potx",
    ".odp",
    ".odt",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlt",
    ".xltx",
}
SUPPORTED_FILE_TYPES = OFFICE_FILE_TYPES | {
    ".pdf",
    ".png",
    ".jpeg",
    ".jpg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
ENDPOINTS = {
    "parse": "/mineru",
    "images": "/mineru_with_images",
    "two-stage": "/two_stage/task",
}
KNOWN_PATHS = tuple(
    sorted(
        {*ENDPOINTS.values(), "/mineru/task", "/mineru_with_images/task"},
        key=len,
        reverse=True,
    )
)


def validate_file_type(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_FILE_TYPES:
        raise ValueError(
            "Unsupported file extension; supported: "
            + ", ".join(sorted(SUPPORTED_FILE_TYPES))
        )


def resolve_endpoint(
    base: str, mode: str | None, asynchronous: bool
) -> tuple[str, str, str, bool]:
    url = parse.urlsplit(base.strip())
    if (
        url.scheme not in {"http", "https"}
        or not url.netloc
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "API URL must be HTTP(S), without credentials, query, or fragment."
        )
    path = url.path.rstrip("/")
    known = next(
        (candidate for candidate in KNOWN_PATHS if path.endswith(candidate)), None
    )
    if known:
        inferred = (
            "two-stage"
            if known.startswith("/two_stage")
            else "images"
            if "images" in known
            else "parse"
        )
        if mode is not None and inferred != mode:
            raise ValueError(
                "Explicit mode conflicts with the configured endpoint; configure a base URL."
            )
        mode = inferred
        asynchronous |= known.endswith("/task")
        path = path[: -len(known)]
    mode = mode or "parse"
    asynchronous |= mode == "two-stage"
    endpoint_path = ENDPOINTS[mode]
    if asynchronous and mode != "two-stage":
        endpoint_path += "/task"
    root = parse.urlunsplit((url.scheme, url.netloc, path, "", ""))
    return root, root + endpoint_path, mode, asynchronous


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A changed service location must not receive a credential or document silently.
        return None


@contextmanager
def response_deadline(response, deadline: float | None):
    """Interrupt even http.client's internal chunk framing/trailer reads."""
    if deadline is None:
        yield None
        return
    http_response = response.fp if isinstance(response, error.HTTPError) else response
    transport = getattr(
        getattr(getattr(http_response, "fp", None), "raw", None), "_sock", None
    )
    if transport is None:
        raise RuntimeError("Cannot enforce deadline on this HTTP response transport.")

    def interrupt():
        try:
            transport.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # The response may have closed just before the deadline fired.

    timer = Timer(max(0, deadline - time.monotonic()), interrupt)
    timer.daemon = True
    timer.start()
    try:
        yield transport
    finally:
        timer.cancel()


class Client:
    def __init__(self, token: str, timeout: float = 600, insecure: bool = False):
        self.token = token
        self.timeout = timeout
        context = (
            ssl._create_unverified_context()
            if insecure
            else ssl.create_default_context()
        )
        self.opener = request.build_opener(
            NoRedirect(), request.HTTPSHandler(context=context)
        )

    def call(
        self,
        method: str,
        url: str,
        *,
        fields=None,
        file: Path | None = None,
        timeout=None,
        deadline: float | None = None,
    ) -> tuple[int, object]:
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
        }
        data = None
        if file is not None:
            boundary = "tiangong-" + uuid.uuid4().hex
            parts = []
            for name, value in (fields or {}).items():
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                )
            filename = file.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
            prefix = (
                b"".join(parts)
                + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            )
            suffix = f"\r\n--{boundary}--\r\n".encode()

            def body():
                yield prefix
                with file.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        yield chunk
                yield suffix

            data = body()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
            headers["Content-Length"] = str(
                len(prefix) + file.stat().st_size + len(suffix)
            )
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=timeout or self.timeout)
        except error.HTTPError as exc:
            response = exc
        except (
            error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            HTTPException,
        ) as exc:
            raise RuntimeError(
                "HTTP transport failed; submission may still be running."
                if method == "POST"
                else "HTTP status query failed."
            ) from exc
        with response, response_deadline(response, deadline) as transport:
            status = response.code
            try:
                if deadline is None:
                    data = response.read()
                else:
                    # read() may wait forever on a trickling response. read1()
                    # performs at most one raw read so we can check the budget.
                    chunks = []
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                "Polling deadline reached while reading response."
                            )
                        if transport is not None:
                            transport.settimeout(min(self.timeout, remaining))
                        chunk = response.read1(65536)
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "Polling deadline reached while reading response."
                            )
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if response.isclosed():
                            break
                    if response.length not in (None, 0):
                        raise HTTPException(
                            "Response ended before its declared length."
                        )
                    data = b"".join(chunks)
                payload = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeError):
                payload = None
            except (OSError, HTTPException) as exc:
                raise RuntimeError(
                    "HTTP response was interrupted; preserve the request record and resume the saved task if available."
                ) from exc
        return status, payload

    def require(self, method: str, url: str, **kwargs) -> dict:
        status, payload = self.call(method, url, **kwargs)
        if not 200 <= status < 300:
            raise RuntimeError(
                f"HTTP {status}; check authentication, endpoint, or service logs."
            )
        if not isinstance(payload, dict):
            raise TypeError("API did not return a JSON object.")
        return payload


def dereference(schema: dict, value: dict) -> dict:
    seen = set()
    while "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/") or ref in seen:
            raise ValueError("Unsupported OpenAPI reference.")
        seen.add(ref)
        value = schema
        for name in ref[2:].split("/"):
            value = value[name.replace("~1", "/").replace("~0", "~")]
    return value


def enum_values(schema: dict, definition: dict) -> list | None:
    definition = dereference(schema, definition)
    if "enum" in definition:
        return definition["enum"]
    values = []
    for branch in definition.get("anyOf", definition.get("oneOf", [])):
        values.extend(enum_values(schema, branch) or [])
    return values or None


def inspect_schema(
    client: Client,
    root: str,
    endpoint: str,
    fields: dict,
    query: dict,
    asynchronous: bool,
) -> dict:
    schema = client.require("GET", root + "/openapi.json")
    try:
        path = endpoint[len(root) :]
        operation = schema["paths"][path]["post"]
        body = dereference(schema, operation["requestBody"])
        definition = dereference(
            schema, body["content"]["multipart/form-data"]["schema"]
        )
        properties = definition["properties"]
        if "file" not in properties:
            raise ValueError("OpenAPI lacks the upload file field.")
        for name, value in fields.items():
            if name not in properties:
                raise ValueError(f"OpenAPI lacks form field {name}.")
            choices = enum_values(schema, properties[name])
            if choices and value not in choices:
                raise ValueError(
                    f"Configured {name} is not supported by deployment OpenAPI."
                )
        parameters = schema["paths"][path].get("parameters", []) + operation.get(
            "parameters", []
        )
        query_names = {
            dereference(schema, item).get("name")
            for item in parameters
            if dereference(schema, item).get("in") == "query"
        }
        if not query.keys() <= query_names:
            raise ValueError("OpenAPI lacks required query switches.")
        if asynchronous and "get" not in schema["paths"][path + "/{task_id}"]:
            raise ValueError("OpenAPI lacks the task status route.")
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "Deployment OpenAPI does not match the parsing contract."
        ) from exc
    return schema
