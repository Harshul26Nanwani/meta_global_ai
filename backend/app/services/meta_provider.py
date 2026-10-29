import json
import os
from typing import Any, Dict, List, Optional

import httpx


class MetaProvider:
    def diagnose(self, task_description: str, events: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError


class MockMetaProvider(MetaProvider):
    def diagnose(self, task_description: str, events: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event_ids = [event.get('id') for event in events if event.get('id')]
        if not event_ids:
            raise ValueError('No events available to diagnose; the run must include at least one recorded event.')

        divergence_event = next(
            (event for event in events if event.get('event_type') in {'assertion_evaluated', 'task_failed', 'tool_result'}),
            events[-1],
        )
        primary_event_id = divergence_event.get('id', event_ids[-1])
        supporting = [event_id for event_id in event_ids if event_id != primary_event_id][:3]
        if not supporting:
            supporting = [primary_event_id]

        return {
            'summary': 'The agent selected a product above the task budget without re-checking the budget constraint before completing the task.',
            'suspected_divergence_event_id': primary_event_id,
            'supporting_event_ids': supporting,
            'classification': 'incorrect_action',
            'confidence_estimate': 'medium',
            'alternative_explanations': [
                'The model may have misread the available pricing information.',
                'The task may have been missing a required verification assertion.'
            ],
            'recommended_correction': 'add_verification_step',
            'replay_plan': {
                'type': 'replay_with_verification',
                'success_criteria': ['product_price_under_budget', 'cart_contains_valid_product']
            }
        }


class BasetenMetaProvider(MetaProvider):
    def _build_request(self, task_description: str, events: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event_lines = []
        for index, event in enumerate(events, start=1):
            event_lines.append(
                {
                    'index': index,
                    'id': event.get('id'),
                    'event_type': event.get('event_type'),
                    'status': event.get('status'),
                    'input': event.get('input_payload'),
                    'output': event.get('output_payload'),
                }
            )

        return {
            'model': os.getenv('META_MODEL_ID', 'meta-llama/Llama-3.1-8B-Instruct'),
            'messages': [
                {
                    'role': 'system',
                    'content': (
                        'You diagnose failures in AI agent runs. Return a JSON object matching this schema: '
                        '{summary: string, suspected_divergence_event_id: string, supporting_event_ids: string[], '
                        'classification: string, confidence_estimate: string|number, alternative_explanations: string[], '
                        'recommended_correction: string, replay_plan: {type: string, success_criteria: string[]}}. '
                        'Use real event IDs from the supplied run and prefer the smallest plausible set of supporting evidence.'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps({
                        'task_description': task_description,
                        'metadata': metadata or {},
                        'events': event_lines,
                    }),
                },
            ],
            'temperature': 0.1,
            'max_tokens': 400,
        }

    def _extract_model_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            if 'choices' in payload and isinstance(payload['choices'], list):
                first_choice = payload['choices'][0]
                if isinstance(first_choice, dict):
                    if 'message' in first_choice and isinstance(first_choice['message'], dict):
                        if 'content' in first_choice['message']:
                            return self._extract_model_payload(first_choice['message']['content'])
                    if 'text' in first_choice:
                        return self._extract_model_payload(first_choice['text'])
            if 'content' in payload:
                return self._extract_model_payload(payload['content'])
            if 'output' in payload:
                return self._extract_model_payload(payload['output'])
            if 'result' in payload:
                return self._extract_model_payload(payload['result'])
            if 'message' in payload and isinstance(payload['message'], dict):
                return self._extract_model_payload(payload['message'])
            if 'data' in payload and isinstance(payload['data'], list):
                return self._extract_model_payload(payload['data'][0])
            return payload
        if isinstance(payload, list):
            if not payload:
                return {}
            return self._extract_model_payload(payload[0])
        if isinstance(payload, str):
            text = payload.strip()
            if text.startswith('```'):
                cleaned = text.strip('`')
                if cleaned.lower().startswith('json'):
                    cleaned = cleaned[4:].lstrip()
                text = cleaned.strip()
            if text.startswith('{') or text.startswith('['):
                return json.loads(text)
            raise ValueError('Unable to parse the diagnosis payload returned by the model.')
        return payload

    def diagnose(self, task_description: str, events: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        api_key = os.getenv('META_API_KEY')
        base_url = os.getenv('META_BASE_URL')
        if not api_key or not base_url:
            raise RuntimeError(
                'Meta/Baseten configuration is incomplete. Set META_API_KEY and META_BASE_URL, or switch MODEL_PROVIDER to mock.'
            )
        if not events:
            raise ValueError('No events available to diagnose; the run must include at least one recorded event.')

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        request_payload = self._build_request(task_description, events, metadata)

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(base_url, json=request_payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise RuntimeError(f'Meta/Baseten diagnosis request failed: {exc}') from exc

        diagnosis = self._extract_model_payload(data)
        if not isinstance(diagnosis, dict):
            raise ValueError('The diagnosis payload returned by the model was not a JSON object.')
        return diagnosis


def get_meta_provider() -> MetaProvider:
    provider_name = os.getenv('MODEL_PROVIDER', 'mock').lower()
    if provider_name in {'mock', 'local', 'local-demo'}:
        return MockMetaProvider()
    if provider_name in {'baseten', 'meta'}:
        return BasetenMetaProvider()
    return MockMetaProvider()
