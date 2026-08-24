"""Page drivers. The executor is driver-agnostic:

- HttpFormDriver: httpx + stdlib HTML parsing. Handles plain HTML forms
  (mockboard, tests, QA, simple ATS forms). "Screenshots" are HTML snapshots.
- PlaywrightDriver: real Chromium for production sites (JS-heavy ATS forms).
  Requires `pip install 'aijaa[apply]' && playwright install chromium`.
"""

import os
from typing import Protocol
from urllib.parse import urljoin

import httpx

from aijaa.core.config import get_settings


class PageDriver(Protocol):
    current_url: str
    html: str

    async def goto(self, url: str) -> str: ...
    async def fill_form(self, values: dict, files: dict[str, str]) -> None: ...
    async def submit_form(self, action: str, method: str, values: dict,
                          files: dict[str, str]) -> str: ...
    async def snapshot(self, path: str) -> str: ...
    async def close(self) -> None: ...


class HttpFormDriver:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._owns = client is None
        self.current_url = ""
        self.html = ""
        self.filled_values: dict = {}
        self.filled_files: dict[str, str] = {}

    async def goto(self, url: str) -> str:
        resp = await self._client.get(url)
        resp.raise_for_status()
        self.current_url = str(resp.url)
        self.html = resp.text
        return self.html

    async def fill_form(self, values: dict, files: dict[str, str]) -> None:
        # Plain HTTP has no live DOM to mutate. Retain the approved payload so
        # snapshots/tests can prove preparation occurred before submission.
        self.filled_values = dict(values)
        self.filled_files = dict(files)

    async def submit_form(self, action: str, method: str, values: dict,
                          files: dict[str, str]) -> str:
        await self.fill_form(values, files)
        url = urljoin(self.current_url, action) if action else self.current_url
        file_payload = {}
        opened = []
        try:
            for field, path in files.items():
                f = open(path, "rb")  # noqa: SIM115
                opened.append(f)
                file_payload[field] = (os.path.basename(path), f)
            if method.lower() == "get":
                resp = await self._client.get(url, params=values)
            elif file_payload:
                resp = await self._client.post(url, data=values, files=file_payload)
            else:
                resp = await self._client.post(url, data=values)
        finally:
            for f in opened:
                f.close()
        resp.raise_for_status()
        self.current_url = str(resp.url)
        self.html = resp.text
        return self.html

    async def snapshot(self, path: str) -> str:
        path = path if path.endswith(".html") else path + ".html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- url: {self.current_url} -->\n{self.html}")
        return path

    async def close(self) -> None:
        if self._owns:
            await self._client.aclose()


class PlaywrightDriver:
    """Production driver. Fills the parsed form fields on the live page and
    clicks the real submit control; screenshots are PNGs."""

    def __init__(self):
        self.current_url = ""
        self.html = ""
        self._pw = None
        self._browser = None
        self._page = None

    async def _ensure(self):
        if self._page is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
            self._page = await self._browser.new_page()

    async def goto(self, url: str) -> str:
        await self._ensure()
        await self._page.goto(url, wait_until="domcontentloaded")
        self.current_url = self._page.url
        self.html = await self._page.content()
        return self.html

    async def submit_form(self, action: str, method: str, values: dict,
                          files: dict[str, str]) -> str:
        await self._ensure()
        await self.fill_form(values, files)
        await self._page.locator('button[type="submit"], input[type="submit"]').first.click()
        await self._page.wait_for_load_state("domcontentloaded")
        self.current_url = self._page.url
        self.html = await self._page.content()
        return self.html

    async def fill_form(self, values: dict, files: dict[str, str]) -> None:
        await self._ensure()
        for name, value in values.items():
            locator = self._page.locator(f'[name="{name}"]').first
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                await locator.select_option(label=str(value))
            else:
                itype = await locator.get_attribute("type") or "text"
                if itype in ("checkbox", "radio"):
                    if value:
                        await locator.check()
                else:
                    await locator.fill(str(value))
        for name, path in files.items():
            await self._page.locator(f'[name="{name}"]').first.set_input_files(path)
        self.html = await self._page.content()

    async def snapshot(self, path: str) -> str:
        await self._ensure()
        path = path if path.endswith(".png") else path + ".png"
        await self._page.screenshot(path=path, full_page=True)
        return path

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


def get_driver(client: httpx.AsyncClient | None = None) -> PageDriver:
    kind = getattr(get_settings(), "apply_driver", "http")
    if kind == "playwright":
        try:
            import playwright  # noqa: F401

            return PlaywrightDriver()
        except ImportError:
            import structlog

            structlog.get_logger().warning("playwright_not_installed_falling_back_http")
    return HttpFormDriver(client)
