import json
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from playwright.sync_api import sync_playwright

from app.database import create_event_record, create_run_record, update_run_status
from app.validation import evaluate_assertions

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_APP_DIR = PROJECT_ROOT / 'demo_app'


def _serve_demo_app(port: int = 0):
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
    server, _ = _serve_demo_app()
    demo_url = f'http://127.0.0.1:{server.server_address[1]}'
    run_id = None
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
            try:
                page = browser.new_page()
                page.goto(demo_url)
                page.locator('[data-product-id="powermax-15"] .buy-button').click()
                page.locator('#checkout-button').click()
                selected = page.locator('#selected-product').inner_text()
                total = page.locator('#cart-total').inner_text()
                record_event(run_id, 'tool_result', 'success', {'selected_product': selected, 'cart_total': total}, {'status': 'cart_updated'})
            finally:
                browser.close()

        final_state = {'selected_product': 'PowerMax 15', 'selected_price': 89999, 'budget_limit': 80000}
        record_event(run_id, 'assertion_evaluated', 'failure', {'expected': 'under_80000', 'actual': final_state}, {'result': 'failed'})
        record_event(run_id, 'task_failed', 'failure', {'reason': 'selected product exceeds budget'}, {'message': 'Task failed'})
        update_run_status(run_id, 'failed')
        return {'run_id': run_id, 'state': final_state, 'events': []}
    except Exception:
        if run_id:
            update_run_status(run_id, 'failed')
        raise
    finally:
        server.shutdown()
        server.server_close()


def run_verified_replay(run_id: str, correction_type: str) -> Dict[str, Any]:
    if correction_type != 'add_verification_step':
        raise ValueError(f'No replay implementation exists for correction: {correction_type}')

    server, _ = _serve_demo_app()
    base_url = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        record_event(run_id, 'task_started', 'success', {'correction': correction_type}, {'message': 'Replay started'})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(base_url, wait_until='domcontentloaded')
                budget_text = page.locator('.budget-pill').inner_text()
                budget_limit = int(''.join(re.findall(r'\d', budget_text)))
                products = page.locator('.product-card').evaluate_all(
                    "cards => cards.map(card => ({"
                    "id: card.dataset.productId,"
                    "name: card.querySelector('h2')?.textContent?.trim() || '',"
                    "price: Number(card.dataset.price || 0),"
                    "rating: Number((card.querySelector('.rating')?.textContent || '').replace(/[^0-9.]/g, ''))"
                    "}))"
                )
                if not products:
                    raise RuntimeError('The storefront did not expose any products.')

                initial_product = max(products, key=lambda product: product['rating'])
                page.locator(f'.product-card[data-product-id="{initial_product["id"]}"] .buy-button').click()
                initial_price = int(page.locator(f'.product-card[data-product-id="{initial_product["id"]}"]').get_attribute('data-price'))
                initial_state = {
                    'selected_product': initial_product['name'],
                    'selected_price': initial_price,
                    'budget_limit': budget_limit,
                }
                initial_assertions = evaluate_assertions(initial_state)
                record_event(
                    run_id,
                    'tool_result',
                    'success',
                    initial_state,
                    {'cart_selection_observed': True},
                )

                if not initial_assertions['assertion_passed']:
                    record_event(
                        run_id,
                        'assertion_evaluated',
                        'failure',
                        initial_state,
                        {**initial_assertions, 'correction_triggered': True},
                    )
                    eligible_products = [product for product in products if product['price'] <= budget_limit]
                    if not eligible_products:
                        raise RuntimeError('No product satisfies the task budget.')
                    selected_product = max(eligible_products, key=lambda product: product['rating'])
                    record_event(
                        run_id,
                        'model_decision',
                        'success',
                        {'budget_limit': budget_limit, 'candidates': len(eligible_products)},
                        {'selected_product': selected_product['name'], 'reason': 'highest-rated product within budget'},
                    )
                    page.locator(f'.product-card[data-product-id="{selected_product["id"]}"] .buy-button').click()
                else:
                    selected_product = initial_product

                page.locator('#checkout-button').click()
                verification_text = page.locator('#selected-product').inner_text()
                cart_total_text = page.locator('#cart-total').inner_text()
                cart_total = int(''.join(re.findall(r'\d', cart_total_text)))
                final_state = {
                    'selected_product': selected_product['name'],
                    'selected_price': cart_total,
                    'budget_limit': budget_limit,
                }
                assertions = evaluate_assertions(final_state)
                assertions['storefront_verified'] = verification_text.startswith('Verified product:')
                assertions['product_matches_cart'] = selected_product['name'] in verification_text
                assertions['assertion_passed'] = all(assertions.values())
                record_event(
                    run_id,
                    'assertion_evaluated',
                    'success' if assertions['assertion_passed'] else 'failure',
                    final_state,
                    {'verification_text': verification_text, **assertions},
                )
                record_event(
                    run_id,
                    'task_completed' if assertions['assertion_passed'] else 'task_failed',
                    'success' if assertions['assertion_passed'] else 'failure',
                    final_state,
                    {'message': verification_text},
                )
                return {
                    'verification_status': 'verified' if assertions['assertion_passed'] else 'failed',
                    'assertion_results': assertions,
                    'state_diff': {
                        'execution_mode': 'playwright_observed',
                        'selected_product': selected_product['name'],
                        'selected_price': cart_total,
                        'budget_limit': budget_limit,
                        'verification_text': verification_text,
                    },
                }
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    print(json.dumps(run_demo_scenario(), indent=2))
