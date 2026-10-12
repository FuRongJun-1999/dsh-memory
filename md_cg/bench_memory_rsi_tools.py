"""Check the offline RSI pipeline using actual, bounded Python tool executions.

The controller and three repair plans are fixed. This is integration evidence,
not a language-model Agent benchmark or proof of learned task success.
No network, package install, shell command or automatically accepted knowledge.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


PROGRAM = '''import csv, json, sys
from pathlib import Path
kind, mode, folder = sys.argv[1:]
project = Path(folder)
if mode == 'required-unit-check':
    actual = json.loads((project / 'actual-output.json').read_text(encoding='utf-8'))
    passed = actual.get('unit') == 'ms'
    print(json.dumps({'answer': int(passed)}))
    raise SystemExit(0 if passed else 1)
elif mode == 'placeholder':
    print(json.dumps({'answer': 'placeholder'}))
elif kind == 'relative-config':
    path = project / 'config.json' if mode == 'repair' else Path('config.json')
    print(json.dumps(json.loads(path.read_text(encoding='utf-8'))))
elif kind == 'json-bom':
    encoding = 'utf-8-sig' if mode == 'repair' else 'utf-8'
    print(json.dumps(json.loads((project / 'config.json').read_text(encoding=encoding))))
elif kind == 'csv-bom':
    encoding = 'utf-8-sig' if mode == 'repair' else 'utf-8'
    with (project / 'config.csv').open(encoding=encoding, newline='') as handle:
        row = next(csv.DictReader(handle))
    print(json.dumps({'answer': int(row['answer'])}))
else:
    raise ValueError('unsupported fixture family')
'''

PLANS = {
    'relative-config': {'action': 'read config.json using the fixture project absolute path',
                        'conditions': ['working directory differs from fixture project root',
                                       'config.json exists in fixture project root']},
    'json-bom': {'action': 'read the UTF-8 BOM JSON fixture using utf-8-sig before json.loads',
                 'conditions': ['JSON file has a UTF-8 BOM', 'loader is Python json.loads']},
    'csv-bom': {'action': 'read the UTF-8 BOM CSV fixture using utf-8-sig before csv.DictReader',
                'conditions': ['CSV file has a UTF-8 BOM', 'header field is answer']}}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def graph_hash(root):
    values = [(p.relative_to(root).as_posix(), sha(p))
              for p in sorted(root.rglob('*')) if p.is_file()]
    return hashlib.sha256(json.dumps(values).encode('utf-8')).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--multicheck', action='store_true', help='include a second required check that fails')
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for name in tuple(os.environ):
        if name.startswith(('MDCG_', 'WB_')):
            os.environ.pop(name)
    for key, folder in (('MDCG_ROOT', 'unused-default'), ('MDCG_DATA_ROOT', 'data'),
                        ('MDCG_AUX_ROOT', 'auxiliary'), ('MDCG_STATE_ROOT', 'state'),
                        ('DSH_HOME', 'dsh'), ('TEMP', 'temporary'), ('TMP', 'temporary')):
        path = out / folder
        path.mkdir(exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(WB_MD_DIRECT='0', WB_MD_ROOT=str(out / 'absent-md'),
                      MDCG_SUSTAIN='0', MDCG_SLEEP='0', MDCG_FRESHNESS='0',
                      PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from .mdcos import MdCGOS
    from .memory_rsi import MemoryRSILab, create_sandbox

    program = out / 'fixture_tool.py'
    program.write_text(PROGRAM, encoding='utf-8')
    receipt_dir = out / 'tool-receipts'
    receipt_dir.mkdir()
    cwd = out / 'empty-working-directory'
    cwd.mkdir()
    protocol = {'controller': 'fixed whitelist; no model and no strategy selection',
                'families': PLANS, 'training_outcomes': ['repair', 'unchanged', 'placeholder']
                    + (['mixed'] if args.multicheck else []),
                'checks': 'returncode == 0 AND parsed stdout equals independent expected value',
                'tool_timeout_seconds': 5, 'max_tool_calls': 30 if args.multicheck else 21,
                'total_repairs': 3, 'multicheck': args.multicheck,
                'automatic_acceptance': False, 'script_sha256': sha(__file__),
                'fixture_tool_sha256': sha(program),
                'agent_task_success': None,
                'caveat': 'Fixed plan replay on constructed files is not an LLM Agent transfer score.'}
    write_json(out / 'protocol.json', protocol)
    calls = []

    def fixture(name, family, expected):
        project = out / 'fixtures' / name
        project.mkdir(parents=True)
        if family == 'csv-bom':
            (project / 'config.csv').write_text('answer\n' + str(expected) + '\n', encoding='utf-8-sig')
        else:
            (project / 'config.json').write_text(json.dumps({'answer': expected}),
                encoding='utf-8-sig' if family == 'json-bom' else 'utf-8')
        return project

    def run(family, mode, project, expected):
        if len(calls) >= protocol['max_tool_calls']:
            raise RuntimeError('tool call budget exceeded')
        if family not in PLANS or mode not in ('repair', 'unchanged', 'placeholder', 'required-unit-check'):
            raise ValueError('plan is outside fixed whitelist')
        argv = [sys.executable, '-X', 'utf8', str(program), family, mode, str(project)]
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=5, shell=False)
        try:
            parsed = json.loads(completed.stdout)
        except (ValueError, TypeError):
            parsed = None
        passed = completed.returncode == 0 and parsed == {'answer': expected}
        record = {'argv': argv, 'cwd': str(cwd), 'returncode': completed.returncode,
                  'stdout': completed.stdout, 'stderr': completed.stderr,
                  'independent_expected': {'answer': expected}, 'passed': passed,
                  'program_sha256': sha(program)}
        path = receipt_dir / f'{len(calls):03}.json'
        write_json(path, record)
        reference = {'file': path.relative_to(out).as_posix(), 'sha256': sha(path),
                     'returncode': completed.returncode}
        calls.append(reference)
        return record, reference

    lab_dir = out / 'lab'
    root = create_sandbox(lab_dir)
    cg = MdCGOS(str(root))
    lab = MemoryRSILab(cg, lab_dir, enabled=True)
    observations, successful, proposal_ids = [], {}, []
    try:
        for family_number, (family, plan) in enumerate(PLANS.items()):
            for outcome_number, mode in enumerate(protocol['training_outcomes']):
                task = family + '-' + mode
                expected = 100 + family_number * 10 + outcome_number
                project = fixture(task, family, expected)
                initial, first = run(family, 'unchanged', project, expected)
                repaired, second = run(family, 'repair' if mode == 'mixed' else mode, project, expected)
                if initial['passed'] or initial['returncode'] == 0:
                    raise AssertionError('initial fixture must fail visibly')
                error = initial['stderr'].strip().splitlines()[-1]
                action = plan['action'] if mode in ('repair', 'mixed') else 'retry unchanged loader' if mode == 'unchanged' else 'return a placeholder value'
                trace = {'task_id': task, 'scope': 'Python fixture ' + family,
                         'conditions': plan['conditions'], 'events': [
                             {'id': 'error', 'kind': 'error', 'text': error, 'receipt': first},
                             {'id': 'action', 'kind': 'action', 'text': action,
                              'error_id': 'error', 'receipt': second},
                             {'id': 'check', 'kind': 'check', 'text': 'independent expected output check',
                              'source': 'tool', 'passed': repaired['passed'],
                              'error_id': 'error', 'action_id': 'action', 'receipt': second}]}
                overall_pass = repaired['passed']
                if mode == 'mixed':
                    (project / 'actual-output.json').write_text(repaired['stdout'], encoding='utf-8')
                    extra, third = run(family, 'required-unit-check', project, 1)
                    trace['conditions'] = [*plan['conditions'], 'output also requires unit=ms']
                    trace['events'].append({'id': 'required-unit', 'kind': 'check',
                        'text': 'independent required unit field check', 'source': 'tool',
                        'passed': extra['passed'], 'error_id': 'error', 'action_id': 'action',
                        'receipt': third})
                    overall_pass = overall_pass and extra['passed']
                trace_id = lab.record_experience(trace)
                reflection = lab.reflect(trace_id)
                candidates = reflection['candidates']
                if len(candidates) != int(overall_pass):
                    raise AssertionError('candidate/check mismatch')
                curated = None
                if candidates:
                    candidate = candidates[0]
                    if not lab.verify(candidate)['ok']:
                        raise AssertionError('verified observation lost evidence')
                    curated = lab.curate(candidate)
                    proposal_ids.append(curated['pid'])
                    successful[family] = candidate
                observations.append({'task': task, 'mode': mode, 'trace_id': trace_id,
                                     'tool_returncode': repaired['returncode'],
                                     'primary_check_passed': repaired['passed'],
                                     'check_passed': overall_pass, 'candidates': len(candidates),
                                     'curation': curated})
        frozen = graph_hash(root)
        replays = []
        for family_number, (family, candidate) in enumerate(successful.items()):
            if candidate.action != PLANS[family]['action']:
                raise AssertionError('action outside frozen repair plan')
            expected = 900 + family_number
            project = fixture(family + '-independent-instance', family, expected)
            record, receipt = run(family, 'repair', project, expected)
            replays.append({'family': family, 'passed': record['passed'], 'receipt': receipt,
                            'source': 'extracted candidate exact-match to fixed plan whitelist'})
        graph_unchanged = frozen == graph_hash(root)
        pending_before = len(cg.review_list())
        rollback = lab.rollback(proposal_ids[0])
        result = {'protocol': protocol, 'observations': observations,
                  'actual_tool_calls': len(calls), 'receipts': calls,
                  'successful_observations': sum(r['check_passed'] for r in observations),
                  'failed_observations': sum(not r['check_passed'] for r in observations),
                  'unsupported_candidates': sum(r['candidates'] for r in observations if not r['check_passed']),
                  'zero_exit_but_failed_check': sum(r['tool_returncode'] == 0 and not r['check_passed'] for r in observations),
                  'independent_instance_plan_replays': replays,
                  'graph_frozen_during_plan_replay': graph_unchanged,
                  'pending_before_rollback': pending_before,
                  'rollback_ok': bool(rollback.get('ok')), 'pending_after_rollback': len(cg.review_list()),
                  'knowledge_nodes_written': sum(entry.get('layer') == 'knowledge' for entry in list(cg.index['nodes'].values())),
                  'agent_task_success': None, 'model': None, 'automatic_acceptance': False,
                  'program_unchanged': sha(program) == protocol['fixture_tool_sha256']}
        write_json(out / 'results.json', result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('protocol', 'observations', 'receipts')},
                         ensure_ascii=False, indent=2))
    finally:
        cg.close()


if __name__ == '__main__':
    main()
