from __future__ import annotations
import asyncio
import time
import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


class _RateLimiter:
    def __init__(self, delay: float):
        self._delay = max(delay, 0.1)
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, domain: str):
        async with self._lock:
            now = time.monotonic()
            gap = self._delay - (now - self._last.get(domain, 0))
            if gap > 0:
                await asyncio.sleep(gap)
            self._last[domain] = time.monotonic()


class CatalogueClient:
    def __init__(self, delay: float = 0.5, timeout: float = 30.0):
        self._limiter = _RateLimiter(delay)
        self._timeout = timeout
        self._session = self._make_curl_session()
        self._httpx_session = httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=timeout,
            http2=True,
        )
        # camoufox: one persistent browser, sequential page opens
        self._cf_browser = None
        self._cf_lock = asyncio.Lock()

    def _make_curl_session(self):
        try:
            from curl_cffi.requests import AsyncSession
            return AsyncSession(impersonate="chrome120", timeout=self._timeout)
        except ImportError:
            return None

    def _domain(self, url: str) -> str:
        try:
            return url.split("/")[2]
        except IndexError:
            return url

    async def get(self, url: str) -> httpx.Response | None:
        domain = self._domain(url)
        for attempt in range(3):
            try:
                await self._limiter.wait(domain)
                if self._session is not None:
                    r = await self._session.get(url, headers=HEADERS, allow_redirects=True)
                    if r.status_code == 429:
                        await asyncio.sleep(min(2 ** attempt * 5, 60))
                        continue
                    return _CurlResponse(r)
                r = await self._httpx_session.get(url)
                if r.status_code == 429:
                    await asyncio.sleep(min(2 ** attempt * 5, 60))
                    continue
                return r
            except Exception:
                if attempt == 2:
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def get_json(self, url: str) -> dict | list | None:
        r = await self.get(url)
        if r and r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
        return None

    async def render(self, url: str) -> str | None:
        """Plain headless Playwright for JS-rendered pages that aren't bot-walled."""
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=UA)
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            html = await page.content()
            await ctx.close()
            await browser.close()
            await pw.stop()
            return html
        except Exception:
            return None

    async def render_stealth(self, url: str, wait_seconds: int = 8) -> str | None:
        """Bypass bot-detection walls using camoufox (Firefox with engine-level
        fingerprint patches: canvas, WebGL, fonts, TLS shape).

        A single persistent browser is reused across calls. Page opens are
        serialized via lock to avoid CDP session conflicts.
        """
        async with self._cf_lock:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._camoufox_render_sync, url, wait_seconds
            )

    def _camoufox_render_sync(self, url: str, wait_seconds: int) -> str | None:
        import time as _time
        try:
            from camoufox.sync_api import Camoufox

            if self._cf_browser is None:
                self._cf_browser = Camoufox(headless=True, humanize=True).__enter__()

            page = self._cf_browser.new_page()
            try:
                page.goto(url, timeout=60_000)
                _time.sleep(wait_seconds)
                page.mouse.move(400, 300)
                _time.sleep(2)
                return page.content()
            finally:
                page.close()
        except Exception as e:
            print(f"  [camoufox] error: {e}", flush=True)
            # Reset on failure so the next call gets a fresh browser
            try:
                if self._cf_browser is not None:
                    self._cf_browser.__exit__(None, None, None)
            except Exception:
                pass
            self._cf_browser = None
            return None

    async def close(self):
        if self._cf_browser is not None:
            try:
                self._cf_browser.__exit__(None, None, None)
            except Exception:
                pass
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
        await self._httpx_session.aclose()


class _CurlResponse:
    """Thin wrapper to make curl_cffi responses look like httpx.Response."""

    def __init__(self, r):
        self._r = r

    @property
    def status_code(self) -> int:
        return self._r.status_code

    @property
    def text(self) -> str:
        return self._r.text

    @property
    def content(self) -> bytes:
        return self._r.content

    def json(self):
        return self._r.json()
