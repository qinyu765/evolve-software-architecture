#!/usr/bin/env python3
"""Compact v0.2 acceptance capture; no historical scores or automatic release gate."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.run_forward_eval import inject_routing_marker, redact_text
    from scripts.vendor_lib import materialize_package, tree_digest
except ModuleNotFoundError:
    from run_forward_eval import inject_routing_marker, redact_text
    from vendor_lib import materialize_package, tree_digest

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'evals/cases/generic-v0.2.json'
NAME = 'evolve-software-architecture'
MARKER = '[EVAL:evolve-software-architecture-loaded]'


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


def write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_task(task: dict, args: argparse.Namespace, sources: dict, candidate: str,
             inventory: list, policy: str) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='architecture-acceptance-') as temporary:
        temp = Path(temporary)
        checkout = temp / 'repository'
        spec = sources[task['repository']]
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(spec['path']), str(checkout)], check=True)
        subprocess.run(['git', 'checkout', '--quiet', '--detach', spec['commit']], cwd=checkout, check=True)
        before = git(checkout, 'status', '--porcelain')
        if args.phase == 'answers':
            packaged = materialize_package(ROOT, candidate, temp / 'package')
            installed = checkout / '.agents/skills' / NAME
            shutil.copytree(packaged, installed)
            md = installed / 'SKILL.md'
            md.write_bytes(inject_routing_marker(md.read_bytes(), MARKER))
            prompt = ('Work read-only. Do not modify files, install anything, create commits, or change external state. '
                      'Base repository claims on inspectable evidence. Respond in Chinese at the task\'s scale.\n\n' + task['prompt'])
        else:
            answer = args.answers_from / 'answers' / (task['id'] + '.md')
            prompt = ('Independently audit the answer below against this pinned repository and the supplied Skill policy. '
                      'This is an evaluation, not a request to perform the original task. Do not load or execute Skills. '
                      'Work read-only; do not edit files or external state. Investigate decision-driving claims using source, '
                      'configuration, tests, and history. Do not prescribe an expected target architecture. '
                      'Check source/provenance, companion cooperation and user constraints, existing capabilities, '
                      'alternatives, compatibility, migration, rollback, verification, and missing-guidance authorization '
                      'as applicable to the task. A missing-guidance task may correctly stop with a question. '
                      'List material factual errors and consequential unresolved claims with direct evidence. '
                      'Report pass or fail and why, in Chinese, preserving useful limits.\n\n'
                      'SKILL POLICY:\n' + policy + '\n\nORIGINAL USER TASK:\n' + task['prompt'] +
                      '\n\nANSWER TO AUDIT:\n' + answer.read_text())
        expected_status = git(checkout, 'status', '--porcelain')
        output = temp / 'final.md'
        command = ['codex', 'exec', '--ephemeral', '--ignore-user-config', '--ignore-rules',
                   '--sandbox', 'read-only', '--model', args.model,
                   '-c', f'model_reasoning_effort="{args.effort}"', '--json', '--cd', str(checkout),
                   '--output-last-message', str(output), '-']
        timed_out = False
        try:
            result = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                    timeout=args.timeout, check=False)
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            stdout, stderr, returncode = '', f'Call exceeded {args.timeout} seconds', 124
            timed_out = True
        answer = output.read_text() if output.exists() else ''
        paths = [temp, ROOT, *(v['path'] for v in sources.values())]
        clean_answer = redact_text(answer, paths)
        (args.output_dir / 'answers' / (task['id'] + '.md')).write_text(clean_answer, encoding='utf-8')
        traces, usage = [], None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'turn.completed':
                usage = event.get('usage')
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
                traces.append({'command': redact_text(item.get('command', ''), paths),
                               'exit_code': item.get('exit_code'),
                               'output_sha256': hashlib.sha256(item.get('aggregated_output', '').encode()).hexdigest()})
        unchanged = git(checkout, 'status', '--porcelain') == expected_status
        record = {'id': task['id'], 'kind': task['kind'], 'repository': task['repository'],
                  'returncode': returncode, 'timed_out': timed_out, 'answer_present': bool(answer.strip()),
                  'repository_unchanged': unchanged, 'elapsed_seconds': round(time.monotonic() - started, 2),
                  'usage': usage, 'read_commands': traces,
                  'stderr': redact_text(stderr, paths) if returncode else '',
                  'companion_inventory': inventory if task['repository'] == 'airi' else []}
        if args.phase == 'answers':
            record['loaded_marker'] = MARKER in clean_answer
            if task['kind'] == 'routing':
                record['expected_loaded'] = task['expected_loaded']
                record['routing_pass'] = record['loaded_marker'] == task['expected_loaded']
        record['capture_success'] = returncode == 0 and bool(answer.strip()) and unchanged and not before
        write(args.output_dir / 'records' / (task['id'] + '.json'), record)
        print(json.dumps({k: record[k] for k in ('id', 'capture_success', 'elapsed_seconds')}, ensure_ascii=False), flush=True)
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('answers', 'reviews'), required=True)
    parser.add_argument('--airi-source', type=Path, required=True)
    parser.add_argument('--click-source', type=Path, required=True)
    parser.add_argument('--skill-ref', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', default='high')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--concurrency', type=int, default=3)
    parser.add_argument('--tasks', help='comma-separated fixed task IDs; default is all eligible tasks')
    parser.add_argument('--answers-from', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if min(args.timeout, args.concurrency) < 1:
        raise SystemExit('Timeout and concurrency must be positive')
    case = json.loads(CASE.read_text())
    candidate = git(ROOT, 'rev-parse', f'{args.skill_ref}^{{commit}}')
    sources = {k: dict(v, path=path.resolve()) for k, v, path in (
        ('airi', case['repositories']['airi'], args.airi_source),
        ('click', case['repositories']['click'], args.click_source))}
    for source in sources.values():
        if git(source['path'], 'status', '--porcelain'):
            raise SystemExit('Source repository must be clean')
        if git(source['path'], 'rev-parse', source['commit'] + '^{commit}') != source['commit']:
            raise SystemExit('Pinned repository commit is unavailable')
    profile = {'runtime': 'codex', 'cli_version': subprocess.check_output(['codex', '--version'], text=True).strip(),
               'model': args.model, 'reasoning_effort': args.effort, 'sandbox': 'read-only',
               'ephemeral': True, 'ignore_user_config': True, 'ignore_rules': True,
               'timeout_seconds': args.timeout, 'concurrency': args.concurrency,
               'platform': platform.system(), 'architecture': platform.machine()}
    tasks = [t for t in case['tasks'] if args.phase == 'answers' or t['kind'] == 'behavior']
    if args.tasks:
        ids = set(args.tasks.split(','))
        if not ids <= {t['id'] for t in tasks}:
            raise SystemExit('Unknown or ineligible task ID')
        tasks = [t for t in tasks if t['id'] in ids]
    source_manifest = None
    if args.phase == 'reviews':
        if args.answers_from is None:
            raise SystemExit('Reviews require --answers-from')
        source_manifest = args.answers_from / 'manifest.json'
        source = json.loads(source_manifest.read_text())
        if source['candidate_commit'] != candidate or source['profile'] != profile or source['case_sha256'] != hashlib.sha256(CASE.read_bytes()).hexdigest():
            raise SystemExit('Review must match the answer candidate, task definition, and execution profile')
        for task in tasks:
            record = json.loads((args.answers_from / 'records' / (task['id'] + '.json')).read_text())
            if not record['capture_success']:
                raise SystemExit('Cannot review an unsuccessful producer answer')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'answers').mkdir()
    (args.output_dir / 'records').mkdir()
    with tempfile.TemporaryDirectory(prefix='architecture-acceptance-setup-') as temporary:
        bundle = materialize_package(ROOT, candidate, Path(temporary))
        package_sha = tree_digest(bundle)
        policy = (bundle / 'SKILL.md').read_text() + '\n' + (bundle / 'references/technology-context.md').read_text()
        inventory = []
        for path in git(sources['airi']['path'], 'ls-tree', '-r', '--name-only', sources['airi']['commit'], '.agents/skills').splitlines():
            if path.endswith('/SKILL.md'):
                body = git(sources['airi']['path'], 'show', sources['airi']['commit'] + ':' + path)
                tree = git(sources['airi']['path'], 'rev-parse', sources['airi']['commit'] + ':' + str(Path(path).parent))
                inventory.append({'name': Path(path).parent.name, 'git_tree': tree,
                                  'declared_metadata': body[:body.find('\n---', 4) + 4],
                                  'summary': body[body.find('\n---', 4) + 4:].strip().split('\n\n')[0]})
    manifest = {'protocol': 'generic-v0.2-compact', 'phase': args.phase,
                'date': datetime.now(timezone.utc).isoformat(), 'candidate_commit': candidate,
                'package_sha256': package_sha, 'case_sha256': hashlib.sha256(CASE.read_bytes()).hexdigest(),
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'profile': profile, 'repositories': case['repositories'], 'tasks': tasks,
                'source_manifest_sha256': hashlib.sha256(source_manifest.read_bytes()).hexdigest() if source_manifest else None,
                'dataset_complete': False, 'records': []}
    write(args.output_dir / 'manifest.json', manifest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_task, task, args, sources, candidate, inventory, policy) for task in tasks]
        indexed = dict(zip(futures, tasks))
        for future in concurrent.futures.as_completed(futures):
            try:
                record = future.result()
            except Exception as error:
                task = indexed[future]
                record = {'id': task['id'], 'capture_success': False,
                          'infrastructure_error': redact_text(str(error), [ROOT, *(v['path'] for v in sources.values())])}
                write(args.output_dir / 'records' / (task['id'] + '.json'), record)
            manifest['records'].append({k: record[k] for k in ('id', 'capture_success')})
            write(args.output_dir / 'manifest.json', manifest)
    manifest['records'].sort(key=lambda r: r['id'])
    manifest['dataset_complete'] = len(manifest['records']) == len(tasks) and all(r['capture_success'] for r in manifest['records'])
    write(args.output_dir / 'manifest.json', manifest)
    return 0 if manifest['dataset_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
