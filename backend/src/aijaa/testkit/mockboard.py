"""In-process mock ATS + job board. Serves the fixture application forms and
records submissions, so the executor/validator can be driven end-to-end with
zero network via httpx ASGITransport. Shared by the demo and the E2E tests.

Form routes:
  GET  /forms/{name}          -> the fixture HTML (name = fixture stem)
  POST /submit/{name}         -> confirmation page (records the submission)
Flaky mode (name suffix '__flaky'): first submit-adjacent GET/POST 500s once.
"""

import os
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

FORMS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "fixtures", "forms")

CONFIRM = (
    "<html><body><h1>Thank you for applying!</h1>"
    "<p>Your application has been received. Confirmation number: {ref}.</p></body></html>"
)


def seeded_jobs(base_url: str = "http://mock") -> list[dict]:
    roles = [
        ("single", "Cloudify", "Senior Backend Engineer", "Python FastAPI PostgreSQL Kubernetes"),
        ("multi", "DataStream", "Backend Engineer", "ETL Python PostgreSQL data pipelines"),
        ("captcha", "CaptchaCo", "Platform Engineer", "Python Kubernetes observability"),
    ]
    jobs = []
    for i in range(20):
        form, company, title, keywords = roles[i % len(roles)]
        if i >= 3:
            company = f"{company}-{i}"
            title = title if i % 4 else "Nurse Practitioner"
            keywords = keywords if i % 4 else "patient care nursing license"
        jobs.append(
            {
                "id": i + 1,
                "title": title,
                "absolute_url": f"{base_url}/forms/{form}",
                "location": {"name": "Tel Aviv" if i % 2 else "Remote"},
                "updated_at": datetime(2026, 7, 16, tzinfo=UTC).isoformat(),
                "content": f"<p>{company} hiring {title}. Requirements: {keywords}.</p>",
                "company": company,
            }
        )
    return jobs


def create_mock_ats() -> FastAPI:
    app = FastAPI(title="Mock ATS")
    app.state.submissions = []  # list of (name, form values)
    app.state.flaky_hits = {}

    @app.get("/v1/boards/{org}/jobs")
    async def greenhouse_jobs(org: str, request: Request):
        base = str(request.base_url).rstrip("/")
        jobs = seeded_jobs(base)
        return JSONResponse({"jobs": [{**j, "company": org if org != "mock" else j["company"]} for j in jobs]})

    @app.get("/forms/{name}", response_class=HTMLResponse)
    async def form(name: str):
        if name == "single":
            name = "greenhouse_simple"
        elif name == "multi":
            name = "comp_question"
        elif name == "captcha":
            name = "captcha_wall"
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
