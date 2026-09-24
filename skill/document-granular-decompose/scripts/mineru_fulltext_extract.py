#!/usr/bin/env python3
"""Parse documents through MinerU, retaining page evidence and resumable tasks."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Keep the distributed Skill directly executable and importable without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_client import (
    Client,
    resolve_endpoint,
    validate_file_type,
)
from mineru_jobs import execute, output_lock, read_record, resume
from mineru_results import atomic_write, file_digest, fulltext

ENV_API_BASE_URL = "UNSTRUCTURED_API_BASE_URL"
ENV_AUTH_TOKEN = "UNSTRUCTURED_AUTH_TOKEN"


def resolve_api_url(api_url_arg: str) -> str:
    """Retained helper; full /mineru_with_images URLs infer image mode."""
    base = api_url_arg.strip() or os.environ.get(ENV_API_BASE_URL, "").strip()
    if not base:
        raise ValueError(f"Missing required environment variable: {ENV_API_BASE_URL}")
    return resolve_endpoint(base, None, False)[1]


def positive(value: str) -> float:
    import math

    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number.")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", help="Local PDF, supported image, or Office document."
    )
    parser.add_argument(
        "--api-url", default="", help="Base URL or known parsing endpoint override."
    )
    parser.add_argument(
        "--mode",
        choices=["parse", "images", "two-stage"],
        help="Default parse; legacy full endpoints infer their mode.",
    )
    parser.add_argument(
        "--tier", choices=["flash", "basic", "standard", "advanced"], default="advanced"
    )
    parser.add_argument(
        "--async",
        dest="asynchronous",
        action="store_true",
        help="Queue parse/images; two-stage is always queued.",
    )
    parser.add_argument(
        "--output-dir",
        help="Evidence bundle and durable task record; required for async.",
    )
    parser.add_argument(
        "--output", default="", help="Optional plain fulltext file (legacy output)."
    )
    parser.add_argument(
        "--resume-only",
        action="store_true",
        help="Only recover a saved request; never submit. --file is optional.",
    )
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--prompt", default=None, help="Optional independent image model instruction."
    )
    parser.add_argument(
        "--timeout",
        type=positive,
        default=600,
        help="HTTP timeout in seconds; not server execution deadline.",
    )
    parser.add_argument(
        "--poll-timeout",
        type=positive,
        default=1800,
        help="Local polling budget including queue wait.",
    )
    parser.add_argument("--poll-interval", type=positive, default=5)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for debugging only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        token = os.environ.get(ENV_AUTH_TOKEN, "").strip()
        if not token:
            raise ValueError(f"Missing required environment variable: {ENV_AUTH_TOKEN}")
        directory = (
            Path(args.output_dir).expanduser().resolve() if args.output_dir else None
        )
        file = Path(args.file).expanduser().resolve() if args.file else None
        output = Path(args.output).expanduser().resolve() if args.output else None
        if file is not None:
            if not file.is_file() or not file.stat().st_size:
                raise ValueError("Input must be a non-empty regular file.")
            validate_file_type(file)
            if output == file or (
                directory is not None and file.is_relative_to(directory)
            ):
                raise ValueError(
                    "Input must be outside the output bundle and must not be overwritten."
                )
        if (
            output is not None
            and directory is not None
            and output.is_relative_to(directory)
        ):
            raise ValueError(
                "--output must be outside the evidence bundle; use its fulltext.txt instead."
            )
        if args.resume_only and (directory is None or not directory.is_dir()):
            raise ValueError("--resume-only requires an existing --output-dir.")
        client = Client(token, args.timeout, args.insecure)
        with output_lock(directory):
            if args.resume_only:
                record = read_record(directory)
                if record is None:
                    raise ValueError("No saved request to resume.")
                if file and file_digest(file) != record["identity"].get("sha256"):
                    raise ValueError("Input content does not match the saved request.")
                # Validate the saved URL; preserve its mode and parameters rather than CLI defaults.
                resolve_endpoint(record["identity"]["endpoint"], None, False)
                payload = resume(
                    client,
                    directory,
                    record,
                    budget=args.poll_timeout,
                    interval=args.poll_interval,
                )
            else:
                if file is None:
                    raise ValueError("--file is required for a new extraction.")
                base = args.api_url or os.environ.get(ENV_API_BASE_URL, "")
                root, endpoint, mode, asynchronous = resolve_endpoint(
                    base, args.mode, args.asynchronous
                )
                if asynchronous and directory is None:
                    raise ValueError(
                        "Async extraction requires --output-dir to persist the task ID."
                    )
                fields = {"tier": args.tier}
                overrides = {
                    "provider": args.provider
                    or os.environ.get("UNSTRUCTURED_PROVIDER"),
                    "model": args.model or os.environ.get("UNSTRUCTURED_MODEL"),
                    "prompt": args.prompt,
                }
                if mode == "parse":
                    if any(getattr(args, name) for name in overrides):
                        raise ValueError(
                            "provider/model/prompt are only valid for image modes."
                        )
                    # Legacy image-model environment settings must not change a plain parse request.
                else:
                    fields.update(
                        {
                            name: value.strip()
                            for name, value in overrides.items()
                            if value and value.strip()
                        }
                    )
                switches = {"chunk_type": "true", "return_txt": "true"}
                query = switches if mode != "two-stage" else {}
                if mode == "two-stage":
                    fields.update(switches)
                identity = {
                    "endpoint": endpoint,
                    "mode": mode,
                    "asynchronous": asynchronous,
                    "sha256": file_digest(file),
                    "filename": file.name,
                    "fields": fields,
                    "query": query,
                }
                payload = execute(
                    client,
                    root=root,
                    identity=identity,
                    file=file,
                    directory=directory,
                    budget=args.poll_timeout,
                    interval=args.poll_interval,
                )
            if output:
                atomic_write(output, fulltext(payload).encode())
            if directory:
                print(str(directory))
            elif output:
                print(str(output))
            else:
                print(fulltext(payload))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        message = str(exc)
        if token:
            message = message.replace(token, "[redacted]")
        print(f"ERROR: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
