"""Form schema extraction from HTML (stdlib parser — no browser needed for
analysis) and interrupt detection (CAPTCHA / login / bot walls)."""

import re
from html.parser import HTMLParser

from pydantic import BaseModel


class FormField(BaseModel):
    name: str
    label: str = ""
    type: str = "text"  # text|email|tel|url|number|textarea|select|checkbox|radio|file|hidden
    required: bool = False
    options: list[str] = []


class FormSchema(BaseModel):
    action: str = ""
    method: str = "post"
    fields: list[FormField] = []
    submit_label: str = "Submit"


CAPTCHA_MARKERS = ("g-recaptcha", "recaptcha", "h-captcha", "hcaptcha", "cf-turnstile",
                   "turnstile", "cf-challenge", "px-captcha", "arkose")
BOTWALL_MARKERS = ("just a moment...", "checking your browser", "attention required")


def detect_interrupts(html: str) -> list[str]:
    lowered = html.lower()
    found = []
    if any(m in lowered for m in CAPTCHA_MARKERS):
        found.append("captcha_present")
    if re.search(r'type=["\']password["\']', lowered):
        found.append("login_required")
    if any(m in lowered for m in BOTWALL_MARKERS):
        found.append("bot_wall")
    if any(m in lowered for m in ("position has been filled", "no longer accepting",
                                  "posting is closed", "job is no longer available")):
        found.append("posting_closed")
    return found


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[FormSchema] = []
        self._form: FormSchema | None = None
        self._labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_buf: list[str] = []
        self._select: FormField | None = None
        self._option_buf: list[str] | None = None
        self._textarea: FormField | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = FormSchema(action=a.get("action", ""), method=a.get("method", "post"))
        elif tag == "label":
            self._label_for = a.get("for") or "__next__"
            self._label_buf = []
        elif self._form is not None and tag == "input":
            itype = (a.get("type") or "text").lower()
            name = a.get("name") or a.get("id") or ""
            if not name or itype in ("submit", "button"):
                if itype == "submit" and a.get("value"):
                    self._form.submit_label = a["value"]
                return
            field = FormField(
                name=name, type=itype, required="required" in a,
                label=self._labels.get(a.get("id") or name, ""),
            )
            if self._label_for == "__next__" and self._label_buf:
                field.label = " ".join(self._label_buf).strip()
            self._form.fields.append(field)
        elif self._form is not None and tag == "textarea":
            name = a.get("name") or a.get("id") or ""
            self._textarea = FormField(
                name=name, type="textarea", required="required" in a,
                label=self._labels.get(a.get("id") or name, ""),
            )
            self._form.fields.append(self._textarea)
        elif self._form is not None and tag == "select":
            name = a.get("name") or a.get("id") or ""
            self._select = FormField(
                name=name, type="select", required="required" in a,
                label=self._labels.get(a.get("id") or name, ""),
            )
            self._form.fields.append(self._select)
        elif tag == "option" and self._select is not None:
            self._option_buf = []
        elif tag == "button" and self._form is not None and a.get("type", "submit") == "submit":
            self._label_buf = []

    def handle_data(self, data):
        if self._label_for is not None:
            self._label_buf.append(data.strip())
        if self._option_buf is not None:
            self._option_buf.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "label" and self._label_for is not None:
            text = " ".join(b for b in self._label_buf if b).strip()
            if self._label_for != "__next__":
                self._labels[self._label_for] = text
                # backfill fields already parsed
                if self._form:
                    for f in self._form.fields:
                        if f.name == self._label_for and not f.label:
                            f.label = text
            self._label_for = None
        elif tag == "option" and self._select is not None and self._option_buf is not None:
            text = " ".join(self._option_buf).strip()
            if text:
                self._select.options.append(text)
            self._option_buf = None
        elif tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


def extract_form(html: str) -> FormSchema | None:
    parser = _FormParser()
    parser.feed(html)
    candidates = [f for f in parser.forms if f.fields]
    if not candidates:
        return None
    return max(candidates, key=lambda f: len(f.fields))
