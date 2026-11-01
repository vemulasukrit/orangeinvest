# Consider it done.

A local errand concierge for the Orange Invest founding engineer assignment. The interface turns a request into a service ticket, then an exact approval, then a verified receipt. No API keys, accounts, real providers, payments, or runtime dependencies.

## Demo

Watch the [3:22 narrated walkthrough on YouTube](https://youtu.be/qEIHA3EPgr4) (unlisted). The local recording is also included as `output/demo.mp4`.

## Run in two commands

Requires Python 3.11 or newer. From this repository:

```sh
python run_evals.py
python server.py
```

Open **http://127.0.0.1:8765**. Keep the terminal running. On systems where Python is named `python3`, substitute it in both commands.

The first command runs the offline evaluation suite and generates `output/eval-results.md`, `output/eval-results.json` and `output/timeout-after-success-trace.json`. The second serves the UI and local API. SQLite persists the application state across restarts. Use `python server.py --port 8766 --db .data/another-demo.db` for an isolated demo.

## Try the whole flow

1. Choose a suggested request, or type “Find a plumber in Indiranagar this week, mornings only, under ₹1,500.” Edit any extracted detail on the ticket.
2. Compare available professionals and select an exact time. The hold’s quote appears on a new review ticket. Nothing is booked yet.
3. Open **Activity**, select **Timeout after success**, and apply the scenario. Approve the ticket.
4. Watch the actual `book` → `get_booking_status` trace and the verified receipt. Repeating “yes” uses the same operation; it does not book twice.
5. Open **Your errands** to prepare a reschedule or cancellation, each requiring a new approval. A cancellation demonstrates the first-call 503 retry.
6. Open **Memory** to save, correct, confirm, or forget stable preferences.

## Why this shape

The distinctive part is deliberately small: the service ticket is also the permission boundary. The backend, not the UI or conversational text, enforces it. The application uses an explicit workflow state machine, owner-bound action fingerprints, durable operation journals, and idempotent mock provider mutations.

The offline interpreter supports the documented home-service vocabulary and common date/time/budget expressions. It is intentionally not an open-ended language model. Structured ticket editing provides a precise fallback. Unknown requests ask for clarification rather than guessing a booking. All displayed prices and providers are mocked.

## Evidence and implementation

- `docs/DESIGN.pdf`: verified two-page design note; editable source in `docs/DESIGN.md`.
- `docs/BUGS.md`: actual defects found while building, fixes and regression tests.
- `docs/REUSE.md`: specific patterns adapted from Arkemis; production repo unchanged.
- `output/eval-results.md`: generated evaluation results.
- `output/timeout-after-success-trace.json`: actual raw recovery trace.
- `docs/demo-script.md`: reproducible demo walkthrough.
- `output/demo.mp4`: narrated demonstration with live interactions and progressive UI transitions; `output/demo.webm` is the equivalent alternate format. Uploading to Loom or YouTube is separate.

`errand/` contains the engine, interpreter, SQLite store and provider mocks. `server.py` is the loopback HTTP boundary. `static/` is the dependency-free browser interface. Tests use temporary databases, never your live demo database.

## Optional browser checks

The application needs no package install. UI automation additionally uses Playwright and installed Google Chrome:

```sh
python -m pip install playwright
python server.py --db .data/ui-test.db --port 8766
# In another terminal, against a fresh database:
python tests/browser_smoke.py --url http://127.0.0.1:8766
```

`python tests/ui_regressions.py` additionally runs seven isolated layout, interaction and motion regression checks. To regenerate the narrated video, see `docs/demo-script.md`.

This checks the live booking and recovery flow, duplicate confirmation, reload, memory forgetting, cancellation, console errors, and mobile overflow. Screenshots are written to `output/`.

## Scope

One local user; loopback binding; no multi-tenant authentication. No optional assignment feature was added before correctness. The production Arkemis project was inspected read-only: no credentials, account data, Electron runtime, or unrelated code was copied.
