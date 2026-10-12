"""Keep the private biometric route in base Compose for future releases."""
import json
import os
from pathlib import Path
import subprocess
import yaml

os.umask(0o077)
root = Path('/opt/v7m-platform/docker-compose.yml')
stage = root.parent / 'releases/selfie-biometric-v97'
original = root.read_bytes()
before = json.loads(subprocess.check_output(['docker', 'compose', '-f', str(root), 'config', '--format', 'json'], text=True))
desired = {'BIOMETRIC_SERVICE_URL': 'http://v7m-biometric:8001', 'BIOMETRIC_TIMEOUT': '30'}
document = yaml.safe_load(original)
for service in ['backend-web', 'backend-qcluster']:
    env = document['services'][service].setdefault('environment', {})
    if isinstance(env, list):
        env = dict(value.split('=', 1) for value in env)
        document['services'][service]['environment'] = env
    env.update(desired)
    before['services'][service].setdefault('environment', {}).update(desired)
backup = stage / 'compose-before-private-biometric.yml'
assert not backup.exists(), 'Base configuration backup already exists'
backup.write_bytes(original)
backup.chmod(0o600)
try:
    root.write_text(yaml.safe_dump(document, sort_keys=False))
    after = json.loads(subprocess.check_output(['docker', 'compose', '-f', str(root), 'config', '--format', 'json'], text=True))
    assert after == before, 'Unexpected base configuration drift'
    print(json.dumps({'persisted': True, 'changed_keys': sorted(desired), 'other_configuration_unchanged': True}))
except Exception:
    root.write_bytes(original)
    raise
