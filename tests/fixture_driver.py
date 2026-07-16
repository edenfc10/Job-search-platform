"""Test PageDriver: serves local fixture forms and canned submit responses,
so the executor/validator can be exercised without a browser or network."""

import os

FORMS_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "forms")

CONFIRM_PAGE = (
    "<html><body><h1>Thank you for applying!</h1>"
    "<p>Your application has been received. Confirmation number: APP-2026-77123.</p>"
    "</body></html>"
)
ERROR_PAGE = "<html><body><h1>Error</h1><p>There was a problem submitting.</p></body></html>"


class FixtureDriver:
    def __init__(self, form_file: str, submit_result: str = "confirm", raise_on_submit: bool = False):
        self._form_file = form_file
        self._submit_result = submit_result
        self._raise_on_submit = raise_on_submit
        self.current_url = ""
        self.html = ""
        self.snapshots: list[str] = []
        self.submit_calls = 0

    async def goto(self, url: str) -> str:
        self.current_url = url
        with open(os.path.join(FORMS_DIR, self._form_file), encoding="utf-8") as f:
            self.html = f.read()
        return self.html

    async def submit_form(self, action, method, values, files) -> str:
        self.submit_calls += 1
        if self._raise_on_submit:
            raise ConnectionError("connection reset after submit")
        self.html = CONFIRM_PAGE if self._submit_result == "confirm" else ERROR_PAGE
        return self.html

    async def snapshot(self, path: str) -> str:
        path = path if path.endswith((".html", ".png")) else path + ".html"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.html)
        self.snapshots.append(path)
        return path

    async def close(self) -> None:
        pass
