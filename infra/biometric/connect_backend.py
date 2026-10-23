"""Run on the Azure host after /health confirms the model loaded. No secret output."""
import json
from pathlib import Path
import subprocess
import time

ROOT = Path('/opt/v7m-platform')
STAGE = ROOT / 'releases/selfie-biometric-v97'
NAMES = ['v7m-backend-web', 'v7m-backend-qcluster']


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


before = {name: inspect(name) for name in NAMES}
files = before[NAMES[0]]['Config']['Labels']['com.docker.compose.project.config_files'].split(',')
assert all(before[name]['Config']['Labels']['com.docker.compose.project.config_files'].split(',') == files for name in NAMES)
command = ['docker', 'compose', '--project-directory', str(ROOT)]
for file in files:
    command += ['-f', file]
probe = "import json,urllib.request; d=json.load(urllib.request.urlopen('http://v7m-biometric:8001/health',timeout=5)); assert d['loaded'] is True; print('model-ready')"
assert run(['docker', 'exec', NAMES[0], 'python', '-c', probe]) == 'model-ready'
overlay = STAGE / 'backend.override.json'
overlay.write_text(json.dumps({'services': {service: {'environment': {
    'BIOMETRIC_SERVICE_URL': 'http://v7m-biometric:8001', 'BIOMETRIC_TIMEOUT': '30'
}} for service in ['backend-web', 'backend-qcluster']}}))
forward = command + ['-f', str(overlay)]
config = json.loads(run(forward + ['config', '--format', 'json']))
allowed = {'BIOMETRIC_SERVICE_URL', 'BIOMETRIC_TIMEOUT'}
for name, old in before.items():
    service = old['Config']['Labels']['com.docker.compose.service']
    expected = config['services'][service]
    env = dict(pair.split('=', 1) for pair in old['Config']['Env'])
    assert expected['image'] == old['Config']['Image'], 'Image drift'
    changed = {key for key, value in expected['environment'].items() if str(value) != env.get(key)}
    assert changed <= allowed, 'Unexpected environment drift: ' + ','.join(changed)

try:
    run(forward + ['up', '-d', '--no-deps', '--no-build', 'backend-web', 'backend-qcluster'])
    for name, old in before.items():
        current = inspect(name)
        assert current['Image'] == old['Image']
        old_env = dict(pair.split('=', 1) for pair in old['Config']['Env'])
        new_env = dict(pair.split('=', 1) for pair in current['Config']['Env'])
        changed = {k for k in old_env.keys() | new_env.keys() if old_env.get(k) != new_env.get(k)}
        assert changed <= allowed, 'Runtime environment drift'
        assert run(['docker', 'exec', name, 'python', '-c', probe]) == 'model-ready'
    health = None
    for _ in range(15):
        try:
            health = json.loads(run(['docker', 'exec', NAMES[0], 'python', '-c', "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/healthz',timeout=4).read().decode())"]))
            assert health['db'] is True and health['migrations_pending'] == 0
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError('Backend did not become healthy')
    evidence = {'connected': True, 'health': health, 'rollback_compose_files': files,
                'biometric_image': inspect('v7m-biometric')['Image'], 'changed_env_keys': sorted(allowed)}
    (STAGE / 'connection-result.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
except Exception:
    run(command + ['up', '-d', '--no-deps', '--no-build', 'backend-web', 'backend-qcluster'])
    raise
