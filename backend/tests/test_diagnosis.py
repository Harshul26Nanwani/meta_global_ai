import json

import httpx
from fastapi.testclient import TestClient

from app.main import app


def test_baseten_provider_parses_model_response(monkeypatch):
    calls = {}

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError('bad response')

        def json(self):
            return self._payload

    def fake_post(self, url, *, json=None, headers=None, timeout=None):
        calls['url'] = url
        calls['json'] = json
        return FakeResponse({
            'choices': [{
                'message': {
                    'content': __import__('json').dumps({
                        'summary': 'The agent ignored the budget limit.',
                        'suspected_divergence_event_id': 'evt-2',
                        'supporting_event_ids': ['evt-1', 'evt-2'],
                        'classification': 'incorrect_action',
                        'recommended_correction': 'add_verification_step',
                        'replay_plan': {'type': 'replay_with_verification'}
                    })
                }
            }]
        })

    monkeypatch.setenv('META_API_KEY', 'secret-key')
    monkeypatch.setenv('META_BASE_URL', 'https://example.com/v1/chat/completions')
    monkeypatch.setenv('MODEL_PROVIDER', 'baseten')
    monkeypatch.setattr(
        httpx,
        'Client',
        lambda *args, **kwargs: type(
            'DummyClient',
            (),
            {'__enter__': lambda self: self, '__exit__': lambda self, exc_type, exc_val, exc_tb: None, 'post': fake_post},
        )(),
    )

    from app.services.meta_provider import BasetenMetaProvider

    provider = BasetenMetaProvider()
    payload = provider.diagnose(
        'Find a laptop under ₹80,000 and add it to the cart.',
        [
            {'id': 'evt-1', 'event_type': 'task_started', 'status': 'success'},
            {'id': 'evt-2', 'event_type': 'assertion_evaluated', 'status': 'failure'},
        ],
    )

    assert payload['recommended_correction'] == 'add_verification_step'
    assert payload['suspected_divergence_event_id'] == 'evt-2'
    assert calls['url'] == 'https://example.com/v1/chat/completions'


def test_diagnosis_uses_real_run_event_ids():
    client = TestClient(app)
    run_response = client.post('/api/runs', json={
        'task_description': 'Find a laptop under ₹80,000 and add the best cart item.',
        'scenario_id': 'budget-check',
        'agent_version': 'demo-agent-v1',
        'model_provider': 'mock',
        'model_identifier': 'mock-model'
    })
    run_id = run_response.json()['id']

    first_event = client.post(f'/api/runs/{run_id}/events', json={
        'event_type': 'task_started',
        'status': 'success',
        'input_payload': {'task': 'Find laptop under 80000'},
        'output_payload': {'message': 'started'}
    }).json()
    second_event = client.post(f'/api/runs/{run_id}/events', json={
        'event_type': 'assertion_evaluated',
        'status': 'failure',
        'input_payload': {'expected': 'under_80000', 'actual': 89999},
        'output_payload': {'result': 'failed'}
    }).json()

    diagnosis_response = client.post(f'/api/runs/{run_id}/diagnose')
    assert diagnosis_response.status_code == 200, diagnosis_response.text
    body = diagnosis_response.json()
    assert body['suspected_divergence_event_id'] in {first_event['id'], second_event['id']}
    assert body['recommended_correction'] == 'add_verification_step'


def test_diagnosis_of_empty_run_returns_conflict_instead_of_server_error():
    client = TestClient(app)
    run_response = client.post('/api/runs', json={
        'task_description': 'Inspect an empty run.',
        'scenario_id': 'empty-run',
    })
    run_id = run_response.json()['id']

    response = client.get(f'/api/runs/{run_id}/diagnosis')

    assert response.status_code == 409
    assert response.json()['detail'] == 'No events are recorded for this run yet.'
