"""Real stdio MCP smoke in a new sandbox; anonymous read and denied write.

python -m md_cg.probe_memory_rsi_mcp --out /new/output
Does not install a DSH plugin or enable Memory-RSI in the server.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for key, name in (('MDCG_ROOT', 'graph'), ('MDCG_DATA_ROOT', 'data'),
                      ('MDCG_STATE_ROOT', 'state'), ('MDCG_AUX_ROOT', 'auxiliary'),
                      ('DSH_HOME', 'dsh'), ('MDCG_TENANT_REGISTRY', 'tenants.json')):
        os.environ[key] = str(out / name)
    for key in ('MDCG_TOKEN', 'MDCG_MASTER_KEY', 'MDCG_TENANT', 'MDCG_THEORY_FILE'):
        os.environ.pop(key, None)
    os.environ.update(MDCG_LEGACY_ENV_AUTH='0', MDCG_SUSTAIN='0', MDCG_SLEEP='0')
    from .mdcos import MdCGOS
    cg = MdCGOS(str(out / 'graph'))
    try:
        cg.add('mcp_fixture', 'Quartz recovery: restore the configuration backup.',
               layer='knowledge', verification_basis='data', sensitivity='public')
        cg.flush()
    finally:
        cg.close()
    def call(rid, arguments):
        return {'jsonrpc': '2.0', 'id': rid, 'method': 'tools/call',
                'params': {'name': 'cg', 'arguments': arguments}}
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        call(3, {'op': 'info'}),
        call(4, {'op': 'read', 'query': 'Quartz recovery', 'k': 3}),
        call(5, {'op': 'write', 'id': 'guest_must_not_write', 'content': 'unauthorized probe'}),
        {'jsonrpc': '2.0', 'id': 6, 'method': 'shutdown'}]
    run = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'md_cg.mcp_server'],
        input=''.join(json.dumps(r) + '\n' for r in requests), text=True,
        capture_output=True, encoding='utf-8', timeout=30, cwd=Path(__file__).resolve().parents[1])
    responses = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    by_id = {r['id']: r for r in responses}
    checks = {'server_exit_zero': run.returncode == 0,
              'initialize': 'serverInfo' in by_id.get(1, {}).get('result', {}),
              'cg_tool_listed': any(t['name'] == 'cg' for t in by_id.get(2, {}).get('result', {}).get('tools', [])),
              'info_succeeded': by_id.get(3, {}).get('result', {}).get('isError') is False,
              'read_fixture': 'restore the configuration backup' in json.dumps(by_id.get(4, {})),
              'guest_write_denied': by_id.get(5, {}).get('result', {}).get('isError') is True
                                    and 'AccessDenied' in json.dumps(by_id.get(5, {}))}
    result = {'checks': checks, 'returncode': run.returncode, 'requests': requests,
              'responses': responses, 'stderr': run.stderr,
              'dsh_profile_installed': False, 'memory_rsi_mcp_integration': 'not_implemented'}
    (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
