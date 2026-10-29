import pytest

from app.validation import (
    ALLOWED_CORRECTIONS,
    evaluate_assertions,
    parse_diagnosis,
    validate_correction,
    validate_event_type,
)


def test_event_validation_accepts_supported_types():
    assert validate_event_type('task_started') is True
    assert validate_event_type('task_failed') is True
    assert validate_event_type('not_real') is False


def test_diagnosis_parser_requires_fields():
    payload = {
        'summary': 'The agent chose an over-budget item.',
        'suspected_divergence_event_id': 'evt-7',
        'supporting_event_ids': ['evt-4', 'evt-7'],
        'classification': 'incorrect_action',
        'recommended_correction': 'add_verification_step',
        'replay_plan': {'type': 'replay_with_verification'},
    }
    parsed = parse_diagnosis(payload)
    assert parsed['classification'] == 'incorrect_action'
    assert parsed['recommended_correction'] == 'add_verification_step'

    with pytest.raises(ValueError):
        parse_diagnosis({'summary': 'No event id'})


def test_correction_validation_rejects_unsupported_corrections():
    assert validate_correction({'type': 'add_verification_step'}, {'add_verification_step'}) is True
    assert validate_correction({'type': 'rm_rf'}, {'rm_rf'}) is False
    assert validate_correction({'type': 'add_verification_step'}, {'correct_tool_argument'}) is False


def test_assertion_evaluation_flags_budget_violations():
    failed_state = {'selected_product': 'PowerMax 15', 'selected_price': 89999, 'budget_limit': 80000}
    passed_state = {'selected_product': 'BudgetPro 14', 'selected_price': 69999, 'budget_limit': 80000}

    failed = evaluate_assertions(failed_state)
    passed = evaluate_assertions(passed_state)

    assert failed['within_budget'] is False
    assert failed['assertion_passed'] is False
    assert passed['assertion_passed'] is True
    assert 'add_verification_step' in ALLOWED_CORRECTIONS
