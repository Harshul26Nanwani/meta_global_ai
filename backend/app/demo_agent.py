import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.database import create_event_record, create_run_record

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_APP_DIR = PROJECT_ROOT / 'demo_app'


def _serve_demo_app(port: int = 8000):
    handler = partial(SimpleHTTPRequestHandler, directory=str(DEMO_APP_DIR))
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def record_event(run_id: str, event_type: str, status: str, input_payload=None, output_payload=None):
    return create_event_record(
        run_id=run_id,
        event_type=event_type,
        status=status,
        input_payload=input_payload or {},
        output_payload=output_payload or {},
        artifact_references=[],
    )


def run_demo_scenario():
    server, _ = _serve_demo_app(8000)
    try:
        run = create_run_record(
            task_description='Find a laptop under ₹80,000, add the best suitable product to the cart, and verify the cart contains the correct product.',
            scenario_id='laptop-misprice',
            agent_version='demo-agent-v1',
            model_provider='local-demo',
            model_identifier='demo-agent',
            status='running',
            metadata={'scenario': 'mispriced_product_selection'}
        )
        run_id = run['id']

        record_event(run_id, 'task_started', 'success', {'task': 'Find a laptop under ₹80,000.'}, {'message': 'Task started'})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('http://127.0.0.1:8000')
            page.locator('[data-product-id="powermax-15"] .buy-button').click()
            page.locator('#checkout-button').click()
            selected = page.locator('#selected-product').inner_text()
            total = page.locator('#cart-total').inner_text()
            record_event(run_id, 'tool_result', 'success', {'selected_product': selected, 'cart_total': total}, {'status': 'cart_updated'})
            browser.close()

        final_state = {'selected_product': 'PowerMax 15', 'selected_price': 89999, 'budget_limit': 80000}
        record_event(run_id, 'assertion_evaluated', 'failure', {'expected': 'under_80000', 'actual': final_state}, {'result': 'failed'})
        record_event(run_id, 'task_failed', 'failure', {'reason': 'selected product exceeds budget'}, {'message': 'Task failed'})
        return {'run_id': run_id, 'state': final_state, 'events': []}
    finally:
        server.shutdown()


if __name__ == '__main__':
    print(json.dumps(run_demo_scenario(), indent=2))
