from fastapi.testclient import TestClient

from app.main import app


def test_health_check():
    client = TestClient(app)
    response = client.get('/api/health')
    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'


def test_create_run_and_ingest_events():
    client = TestClient(app)
    run_response = client.post('/api/runs', json={
        'task_description': 'Find a laptop under ₹80,000 and add the best suited product to cart.',
        'scenario_id': 'laptop-misprice',
        'agent_version': 'demo-agent-v1',
        'model_provider': 'local-demo',
        'model_identifier': 'demo-agent'
    })
    assert run_response.status_code == 200, run_response.text
    run_id = run_response.json()['id']

    event_response = client.post(f'/api/runs/{run_id}/events', json={
        'event_type': 'task_started',
        'status': 'success',
        'input_payload': {'task': 'Find a laptop under ₹80,000.'},
        'output_payload': {'message': 'Task started'},
        'artifact_references': []
    })
    assert event_response.status_code == 200, event_response.text
    payload = event_response.json()
    assert payload['event_type'] == 'task_started'
    assert payload['run_id'] == run_id

    list_response = client.get(f'/api/runs/{run_id}/events')
    assert list_response.status_code == 200
    assert len(list_response.json()['events']) >= 1

    run_summary = next(run for run in client.get('/api/runs').json()['runs'] if run['id'] == run_id)
    assert run_summary['event_count'] == 1
    assert run_summary['failed_event_count'] == 0


def test_replay_returns_verification_status():
    client = TestClient(app)
    run_response = client.post('/api/runs', json={
        'task_description': 'Find a laptop under ₹80,000 and add the right product to cart.',
        'scenario_id': 'laptop-misprice',
        'agent_version': 'demo-agent-v1',
        'model_provider': 'local-demo',
        'model_identifier': 'demo-agent'
    })
    run_id = run_response.json()['id']

    replay_response = client.post(f'/api/runs/{run_id}/replay', json={
        'correction': {'type': 'add_verification_step', 'target': 'cart_check'},
        'allowlist': ['add_verification_step']
    })
    assert replay_response.status_code == 200, replay_response.text
    body = replay_response.json()
    assert 'replay_run_id' in body
    assert 'verification_status' in body
