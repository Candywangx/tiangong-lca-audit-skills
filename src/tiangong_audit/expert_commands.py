"""Read-only expert commands. Private projections never go to standard output."""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from tiangong_audit.experts.binding import bind_roster
from tiangong_audit.experts.context import prepare_context
from tiangong_audit.experts.importer import import_roster
from tiangong_audit.experts.recommendation import validate_recommendations
from tiangong_audit.experts.workspace import private_directory, write_private_bytes, write_snapshot
from tiangong_audit.integrations.tiangong_api import TiangongAPIClient
from tiangong_audit.integrations.tiangong_api.experts import ExpertAPI


def _read(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def run_expert_command(args: argparse.Namespace) -> int:
    try:
        directory = private_directory(args.directory)
        if args.expert_command == 'import':
            roster = import_roster(Path(args.csv))
            source_bytes = Path(args.csv).read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != roster['source_sha256']:
                raise ValueError('CSV changed while importing; retry against a stable source')
            raw = write_private_bytes(directory / 'imports', 'source', source_bytes, 'csv')
            path = write_snapshot(directory, 'roster', roster)
            summary = {'rows': len(roster['records']), 'roster_path': str(path), 'source_path': str(raw),
                       'admission': dict(Counter(r['admission'] for r in roster['records'])),
                       'rows_with_issues': sum(bool(r['issues']) for r in roster['records']), 'platform_writes': 0}
        elif args.expert_command == 'bind':
            roster = _read(args.roster)
            client = TiangongAPIClient(account_role='admin', allow_writes=False)
            api = ExpertAPI(client)
            members = api.get_all_members()
            users = api.read_users([r['user_id'] for r in members])
            fetched_at = datetime.now(timezone.utc).isoformat()
            bound = bind_roster(roster, members, users, platform_url=client.supabase_url,
                                fetched_at=fetched_at, directory_complete=True)
            member_path = write_snapshot(directory, 'platform-members', members)
            identity_path = write_snapshot(directory, 'platform-identities', users)
            bound['binding_provenance'].update(member_snapshot=str(member_path),
                                               identity_snapshot=str(identity_path))
            path = write_snapshot(directory, 'bindings', bound)
            summary = {'rows': len(bound['records']), 'eligible': sum(r['eligible'] for r in bound['records']),
                       'binding_statuses': dict(Counter(r['binding']['status'] for r in bound['records'])),
                       'directory_count': len(members), 'identity_readback_count': len(users),
                       'bindings_path': str(path), 'platform_writes': 0}
        elif args.expert_command == 'prepare':
            context = prepare_context(Path(args.bindings), [Path(p) for p in args.case_dir], directory)
            path = write_snapshot(directory, 'context', context)
            summary = {'expert_count': len(context['experts']), 'case_count': len(context['datasets']),
                       'context_path': str(path), 'platform_writes': 0}
        else:
            checked = validate_recommendations(_read(args.context), _read(args.result))
            path = write_snapshot(directory, 'recommendation-validation', checked)
            summary = {**checked, 'validation_path': str(path), 'platform_writes': 0}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if checked['valid'] else 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Exception bodies may contain source rows or remote responses. Do not
        # leak them through a terminal transcript or CI log.
        print(f'ERROR: expert command failed ({type(error).__name__}); no assignment performed.', file=sys.stderr)
        return 1


def register_expert_commands(subparsers, *, root: Path) -> None:
    parser = subparsers.add_parser('experts', help='Private roster import, read-only binding and recommendation validation')
    commands = parser.add_subparsers(dest='expert_command', required=True)
    for name in ('import', 'bind', 'prepare', 'validate'):
        command = commands.add_parser(name)
        command.add_argument('--directory', default=str(root / 'cases' / 'expert-directory'),
                             help='Git-ignored cases/expert-directory path; no public output directory')
        if name == 'import':
            command.add_argument('--csv', required=True)
        elif name == 'bind':
            command.add_argument('--roster', required=True)
        elif name == 'prepare':
            command.add_argument('--bindings', required=True)
            command.add_argument('--case-dir', required=True, action='append', help='Existing case directory; repeat for multiple cases')
        else:
            command.add_argument('--context', required=True)
            command.add_argument('--result', required=True)
        command.set_defaults(func=run_expert_command)
