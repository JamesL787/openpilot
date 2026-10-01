"""Exercise the actual route functions without loading device services."""
import ast
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, jsonify, request
import pytest

from openpilot.starpilot.system.starpilot_auto import apk_identity


@pytest.fixture
def endpoint(monkeypatch):
  server = Path(__file__).resolve().parents[1] / 'the_galaxy.py'
  setup = next(node for node in ast.parse(server.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'setup')
  names = {'_starpilot_auto_identity_payload', 'starpilot_auto_identity', 'starpilot_auto_identity_recommended',
           'starpilot_auto_identity_download', 'starpilot_auto_identity_upload'}
  routes = [node for node in setup.body if isinstance(node, ast.FunctionDef) and node.name in names]
  assert len(routes) == len(names)
  state = SimpleNamespace(enabled=True, busy=False, calls=[], checks=[])

  def recommendation_status(*args, **kwargs):
    state.checks.append(kwargs['check'])
    return {'updateAvailable': False}

  def start(**kwargs):
    if state.busy:
      raise apk_identity.IdentityImportError('An import is already running')
    state.calls.append(kwargs)

  job = SimpleNamespace(start=start, status=lambda: {'state': 'idle'}, busy=lambda: state.busy)
  monkeypatch.setattr(apk_identity, 'identity_status', lambda: {'installed': False})
  app = Flask(__name__)
  namespace = {'app': app, 'jsonify': jsonify, 'request': request, 'apk_identity': apk_identity,
               'starpilot_auto_recommendation': SimpleNamespace(status=recommendation_status),
               'starpilot_auto_import': job, 'params': SimpleNamespace(get_bool=lambda _: state.enabled)}
  exec(compile(ast.Module(body=routes, type_ignores=[]), str(server), 'exec'), namespace)
  return app.test_client(), state


def test_recommended_starts_background_import_and_cancels_when_disabled(endpoint):
  client, state = endpoint
  response = client.post('/api/starpilot_auto/identity/recommended', json={'url': 'https://ignored.invalid'})
  assert response.status_code == 202
  assert response.json['job'] == {'state': 'idle'}
  [call] = state.calls
  assert call['recommended'] is True and 'url' not in call and call['enabled']()
  state.enabled = False
  assert not call['enabled']()
  assert client.post('/api/starpilot_auto/identity/recommended').status_code == 409
  assert len(state.calls) == 1


def test_recommended_busy_and_manual_download_remain_available(endpoint):
  client, state = endpoint
  state.busy = True
  response = client.post('/api/starpilot_auto/identity/recommended')
  assert response.status_code == 409 and 'already running' in response.json['error']
  state.busy = False
  response = client.post('/api/starpilot_auto/identity/download', json={'url': 'https://example.test/app.apkm'})
  assert response.status_code == 202
  assert state.calls[0]['url'] == 'https://example.test/app.apkm'
  assert client.post('/api/starpilot_auto/identity/upload').status_code == 400


def test_update_check_is_explicit_and_requires_starpilot_auto_enabled(endpoint):
  client, state = endpoint
  client.get('/api/starpilot_auto/identity')
  client.get('/api/starpilot_auto/identity?check_updates=1')
  client.get('/api/starpilot_auto/identity')
  state.enabled = False
  client.get('/api/starpilot_auto/identity?check_updates=1')
  assert state.checks == [False, True, False, False]
