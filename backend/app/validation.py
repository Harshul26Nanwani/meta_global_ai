from typing import Any, Dict, Iterable, List, Mapping, Sequence

ALLOWED_EVENT_TYPES = {
    'task_started', 'model_decision', 'tool_invocation', 'tool_result',
    'browser_navigation', 'click_or_form', 'screenshot_captured',
    'assertion_evaluated', 'exception', 'task_completed', 'task_failed'
}

ALLOWED_CORRECTIONS = {
    'add_verification_step',
    'correct_tool_argument',
    'refresh_observation',
    'avoid_stale_state',
}


def validate_event_type(event_type: str) -> bool:
    return event_type in ALLOWED_EVENT_TYPES


def validate_correction(correction: Mapping[str, Any], allowlist: Iterable[str]) -> bool:
    if not isinstance(correction, Mapping):
        return False
    correction_type = correction.get('type')
    if correction_type not in ALLOWED_CORRECTIONS:
        return False
    if allowlist is None:
        return False
    return correction_type in set(allowlist)


def parse_diagnosis(payload: Mapping[str, Any]) -> Dict[str, Any]:
    required = {
        'summary',
        'suspected_divergence_event_id',
        'supporting_event_ids',
        'classification',
        'recommended_correction',
        'replay_plan',
    }
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f'Missing diagnosis fields: {sorted(missing)}')

    supporting = payload.get('supporting_event_ids')
    if not isinstance(supporting, list):
        raise ValueError('supporting_event_ids must be a list.')

    if payload.get('suspected_divergence_event_id') is None:
        raise ValueError('The suspected divergence event must be declared.')

    return {
        'summary': str(payload['summary']),
        'suspected_divergence_event_id': str(payload['suspected_divergence_event_id']),
        'supporting_event_ids': [str(item) for item in supporting],
        'classification': str(payload['classification']),
        'confidence_estimate': payload.get('confidence_estimate'),
        'alternative_explanations': list(payload.get('alternative_explanations', [])),
        'recommended_correction': str(payload['recommended_correction']),
        'replay_plan': payload.get('replay_plan', {}),
    }


def evaluate_assertions(state: Mapping[str, Any]) -> Dict[str, Any]:
    product_name = state.get('selected_product', '')
    price = state.get('selected_price', 0)
    budget_limit = state.get('budget_limit', 80000)
    cart_matches = product_name and price <= budget_limit
    return {
        'product_selected': bool(product_name),
        'within_budget': bool(price <= budget_limit),
        'cart_valid': bool(cart_matches),
        'assertion_passed': bool(cart_matches),
    }
