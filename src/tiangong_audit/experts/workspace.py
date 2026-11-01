"""Private, immutable expert artifacts in a Git-ignored case directory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def private_directory(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    root = Path(subprocess.run(['git', '-C', str(ancestor), 'rev-parse', '--show-toplevel'],
                              check=True, capture_output=True, text=True).stdout.strip()).resolve()
    if not path.is_relative_to(root / 'cases' / 'expert-directory'):
        raise ValueError('Expert artifacts must stay in cases/expert-directory')
    relative = path.relative_to(root).as_posix()
    subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--no-index',
                    relative + '/privacy-probe.json'], check=True, capture_output=True)
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--', relative],
                             check=True, capture_output=True, text=True).stdout
    if tracked.strip():
        raise ValueError('The expert directory contains tracked files')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def write_private_bytes(directory: Path, label: str, data: bytes, suffix: str) -> Path:
    if not re.fullmatch('[a-z][a-z0-9-]*', label) or suffix not in {'json', 'csv'}:
        raise ValueError('Invalid artifact name')
    directory = private_directory(directory)
    digest = hashlib.sha256(data).hexdigest()
    path = directory / f'{label}.{digest}.{suffix}'
    subprocess.run(['git', '-C', str(directory), 'check-ignore', '-q', '--no-index', str(path)],
                   check=True, capture_output=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError('Immutable expert snapshot conflict')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    return path


def write_snapshot(directory: Path, label: str, value: dict | list) -> Path:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    return write_private_bytes(directory, label, data, 'json')
