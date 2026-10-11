import io
import json
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def controller():
    path = Path(__file__).resolve().parents[1] / "deploy/release/backend_overlay_remote.py"
    spec = importlib.util.spec_from_file_location("backend_release_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_retries_startup_timeout_and_requires_release_identity(controller, monkeypatch):
    expected = {"db": True, "migrations_pending": 0, "sha": "artifact", "version": "release", "built_at": "time"}
    results = iter([TimeoutError(), expected | {"sha": "old"}, expected])
    calls = []

    def open_request(request, timeout):
        calls.append((request.full_url, request.get_header("Host"), timeout))
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return io.StringIO(json.dumps(result))

    monkeypatch.setattr(controller.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(controller.time, "sleep", lambda _: None)
    actual = controller.probe_health("172.18.0.10", {"artifact_sha256": "artifact", "version": "release"}, {"built_at": "time"})
    assert actual == expected
    assert calls == [("http://172.18.0.10:8000/api/v1/health/healthz", "backend.supletivo.net.br", 5)] * 3


def test_readiness_is_bounded_and_rejects_wrong_build(controller, monkeypatch):
    calls = []

    def open_request(*args, **kwargs):
        calls.append(1)
        return io.StringIO(json.dumps({"db": True, "migrations_pending": 0, "sha": "old"}))

    monkeypatch.setattr(controller.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(controller.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="expected artifact"):
        controller.probe_health("172.18.0.10", {"artifact_sha256": "new", "version": "release"}, {"built_at": "time"})
    assert len(calls) == 10
