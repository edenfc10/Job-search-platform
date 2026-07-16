"""In-process mock ATS + job board. Serves the fixture application forms and
records submissions, so the executor/validator can be driven end-to-end with
zero network via httpx ASGITransport. Shared by the demo and the E2E tests.

Form routes:
  GET  /forms/{name}          -> the fixture HTML (name = fixture stem)
  POST /submit/{name}         -> confirmation page (records the submission)
Flaky mode (name suffix '__flaky'): first submit-adjacent GET/POST 500s once.
"""

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

FORMS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "fixtures", "forms")

CONFIRM = (
    "<html><body><h1>Thank you for applying!</h1>"
    "<p>Your application has been received. Confirmation number: {ref}.</p></body></html>"
)


def create_mock_ats() -> FastAPI:
    app = FastAPI(title="Mock ATS")
    app.state.submissions = []  # list of (name, form values)
    app.state.flaky_hits = {}

    @app.get("/forms/{name}", response_class=HTMLResponse)
    async def form(name: str):
        path = os.path.join(FORMS_DIR, f"{name}.html")
        if not os.path.exists(path):
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        with open(path, encoding="utf-8") as f:
            return f.read()

    @app.post("/submit/{name}", response_class=HTMLResponse)
    async def submit(name: str, request: Request):
        if name.endswith("__flaky") and app.state.flaky_hits.get(name, 0) == 0:
            app.state.flaky_hits[name] = 1
            return HTMLResponse("<h1>Server error</h1>", status_code=500)
        form = await request.form()
        app.state.submissions.append((name, dict(form)))
        ref = f"APP-2026-{1000 + len(app.state.submissions)}"
        return CONFIRM.format(ref=ref)

    return app
