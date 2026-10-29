# TraceBack

TraceBack is a lightweight debugging and replay platform for AI agent runs. The MVP focuses on the first end-to-end loop: record a deterministic browser failure, inspect the evidence, validate a small correction, and replay the scenario without overwriting the original execution history.

## Architecture

- Backend: Python + FastAPI
- Persistence: SQLite
- Demo app: static HTML/JS storefront with a deliberately incorrect product-selection bug
- Browser agent: Playwright-based deterministic demo flow
- Frontend: React + Vite (scaffolded as part of the developer tool UI)

## Phase 1 delivered

- SQLite-backed run and event store
- FastAPI endpoints for creating runs, recording events, diagnosing, and replaying a corrected scenario
- Deterministic demo storefront with a product that exceeds the ₹80,000 budget
- Browser automation that captures the failure and records the original evidence
- Validation helpers for supported event types, diagnosis parsing, correction allowlists, and assertion evaluation
- Tests covering event validation, diagnosis parsing, replay conditions, and assertion evaluation

## Prerequisites

- Python 3.9.x
- Node.js 22+ for the React frontend tooling
- Chromium for Playwright

## Local setup

1. Create and activate a virtual environment.
2. Install backend requirements:

   ```powershell
   cd backend
   python.exe -m pip install -r requirements.txt
   ```

3. Install Playwright browser dependencies:

   ```powershell
   python.exe -m playwright install chromium
   ```

4. Start the backend:

   ```powershell
   cd backend
   python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

5. Run the demo agent:

   ```powershell
   cd backend
   python.exe -m app.demo_agent
   ```

6. Run the automated tests:

   ```powershell
   cd backend
   python.exe -m pytest -q tests
   ```

## Known limitations

- The current Meta model integration is intentionally mocked and must be replaced before final submission.
- Replay validation is intentionally restricted to a small allowlist of supported corrections.
- The local storefront is deterministic and intentionally simplified for evidence-based debugging.
