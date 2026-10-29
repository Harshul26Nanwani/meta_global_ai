import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.database import (
    create_diagnosis_record,
    create_event_record,
    create_replay_record,
    create_run_record,
    get_latest_diagnosis_for_run,
    get_run,
    list_events,
    list_replay_records,
    list_runs,
    update_run_status,
)
from app.models import EventCreate, ReplayRequest, RunCreate
from app.services.meta_provider import get_meta_provider
from app.validation import parse_diagnosis, validate_correction, validate_event_type


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import init_db

    init_db()
    yield


app = FastAPI(title='TraceBack MVP', version='0.1.0', lifespan=lifespan)


@app.get('/api/health')
def health_check():
    return {'status': 'ok', 'service': 'traceback-backend'}


@app.post('/api/runs')
def create_run(payload: RunCreate):
    record = create_run_record(
        task_description=payload.task_description,
        scenario_id=payload.scenario_id,
        agent_version=payload.agent_version,
        model_provider=payload.model_provider,
        model_identifier=payload.model_identifier,
        status=payload.status,
        metadata=payload.metadata,
    )
    return record


@app.get('/api/runs')
def list_runs_endpoint():
    return {'runs': list_runs()}


@app.get('/api/runs/{run_id}')
def get_run_endpoint(run_id: str):
    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Run not found.')
    return record


@app.get('/api/runs/{run_id}/events')
def get_events(run_id: str):
    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Run not found.')
    return {'run_id': run_id, 'events': list_events(run_id)}


@app.post('/api/runs/{run_id}/events')
def post_event(run_id: str, payload: EventCreate):
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail='Run not found.')
    if not validate_event_type(payload.event_type):
        raise HTTPException(status_code=400, detail='Unsupported event type.')
    event = create_event_record(
        run_id=run_id,
        event_type=payload.event_type,
        status=payload.status,
        input_payload=payload.input_payload,
        output_payload=payload.output_payload,
        artifact_references=payload.artifact_references,
    )
    return event


@app.post('/api/runs/{run_id}/diagnose')
def diagnose_run(run_id: str):
    original = get_run(run_id)
    if original is None:
        raise HTTPException(status_code=404, detail='Run not found.')

    events = list_events(run_id)
    if not events:
        raise HTTPException(status_code=409, detail='No events are recorded for this run yet.')

    provider = get_meta_provider()
    raw_diagnosis = provider.diagnose(original['task_description'], events, {'scenario_id': original['scenario_id']})
    diagnosis = parse_diagnosis(raw_diagnosis)

    valid_event_ids = {event['id'] for event in events if event.get('id')}
    if diagnosis['suspected_divergence_event_id'] not in valid_event_ids:
        raise HTTPException(status_code=400, detail='Diagnosis references an event ID that does not exist in this run.')
    invalid_supporting = [event_id for event_id in diagnosis['supporting_event_ids'] if event_id not in valid_event_ids]
    if invalid_supporting:
        raise HTTPException(status_code=400, detail='Diagnosis references unseen supporting event IDs.')

    stored = create_diagnosis_record(
        run_id=run_id,
        summary=diagnosis['summary'],
        suspected_divergence_event_id=diagnosis['suspected_divergence_event_id'],
        supporting_event_ids=diagnosis['supporting_event_ids'],
        classification=diagnosis['classification'],
        confidence_estimate=raw_diagnosis.get('confidence_estimate'),
        alternative_explanations=raw_diagnosis.get('alternative_explanations', []),
        recommended_correction=diagnosis['recommended_correction'],
        replay_plan=diagnosis.get('replay_plan', {}),
    )
    result = {
        'id': stored['id'],
        'run_id': run_id,
        'summary': stored['summary'],
        'suspected_divergence_event_id': stored['suspected_divergence_event_id'],
        'supporting_event_ids': json.loads(stored['supporting_event_ids']),
        'classification': stored['classification'],
        'confidence_estimate': stored['confidence_estimate'],
        'alternative_explanations': json.loads(stored['alternative_explanations']),
        'recommended_correction': stored['recommended_correction'],
        'replay_plan': json.loads(stored['replay_plan']),
    }
    return result


@app.get('/api/runs/{run_id}/diagnosis')
def get_diagnosis(run_id: str):
    original = get_run(run_id)
    if original is None:
        raise HTTPException(status_code=404, detail='Run not found.')

    stored = get_latest_diagnosis_for_run(run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail='Diagnosis has not been run for this session.')

    return {
        'id': stored['id'],
        'run_id': run_id,
        'summary': stored['summary'],
        'suspected_divergence_event_id': stored['suspected_divergence_event_id'],
        'supporting_event_ids': json.loads(stored['supporting_event_ids']),
        'classification': stored['classification'],
        'confidence_estimate': stored['confidence_estimate'],
        'alternative_explanations': json.loads(stored['alternative_explanations']),
        'recommended_correction': stored['recommended_correction'],
        'replay_plan': json.loads(stored['replay_plan']),
    }


@app.post('/api/runs/{run_id}/replay')
def replay_run(run_id: str, payload: ReplayRequest):
    original = get_run(run_id)
    if original is None:
        raise HTTPException(status_code=404, detail='Run not found.')
    requested = payload.correction.get('type') if isinstance(payload.correction, dict) else None
    diagnosis = get_latest_diagnosis_for_run(run_id)
    if diagnosis is None:
        raise HTTPException(status_code=409, detail='Run diagnosis before requesting a replay.')
    if requested != diagnosis['recommended_correction']:
        raise HTTPException(status_code=400, detail='Replay correction must match the diagnosis recommendation.')
    if not validate_correction(payload.correction, {'add_verification_step'}):
        raise HTTPException(status_code=400, detail='This correction is not implemented for replay yet.')

    replay_record = create_run_record(
        task_description=original['task_description'],
        scenario_id=original['scenario_id'],
        agent_version=original['agent_version'],
        model_provider=original['model_provider'],
        model_identifier=original['model_identifier'],
        parent_run_id=run_id,
        status='running',
        metadata={'replay_of': run_id, 'correction': payload.correction},
    )
    try:
        from app.demo_agent import run_verified_replay

        result = run_verified_replay(replay_record['id'], requested)
        update_run_status(replay_record['id'], 'completed' if result['verification_status'] == 'verified' else 'failed')
    except Exception as exc:
        update_run_status(replay_record['id'], 'failed')
        create_event_record(
            run_id=replay_record['id'],
            event_type='exception',
            status='failure',
            input_payload={'correction': requested},
            output_payload={'error': str(exc)},
        )
        raise HTTPException(status_code=502, detail=f'Replay execution failed: {exc}') from exc

    create_replay_record(
        original_run_id=run_id,
        replay_run_id=replay_record['id'],
        diagnosis_id=diagnosis['id'],
        correction_applied=requested,
        verification_status=result['verification_status'],
        assertion_results=result['assertion_results'],
        state_diff=result['state_diff'],
    )

    return {'replay_run_id': replay_record['id'], **result}


@app.get('/api/runs/{run_id}/comparison')
def compare_run(run_id: str):
    original = get_run(run_id)
    if original is None:
        raise HTTPException(status_code=404, detail='Run not found.')
    results = list_replay_records(run_id)
    return {'original_run_id': run_id, 'replays': results}


@app.get('/')
def root():
    return {'message': 'TraceBack backend running.'}
