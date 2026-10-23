"""Log in through Donga's normal SSO UI and retain only Canvas session cookies."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlsplit

from playwright.sync_api import sync_playwright
import requests

from canvas_lms import BASE_URL, CanvasClient, CanvasError


SSO_HOSTS = {
    "canvas.donga.ac.kr", "eclass.donga.ac.kr",
    "dxsso.donga.ac.kr", "login.donga.ac.kr",
}


def _allowed(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in SSO_HOSTS
            and parts.port in (None, 443) and not parts.username and not parts.password)


def _verified_proxy_transport(context):
    """Use Playwright's TLS-verifying HTTP client with the platform CA bundle.

    Chromium does not inherit NODE_EXTRA_CA_CERTS. The HTTP client does, so
    proxied cloud sessions fetch every resource with certificate verification.
    Navigation redirects become fresh navigations because Chromium's redirect
    requests otherwise bypass route handlers. Authentication is still performed
    by the school's own page; no TLS checks or authentication steps are disabled.
    """
    issues = []
    def route_request(route):
        request = route.request
        if not _allowed(request.url):
            if request.is_navigation_request() or request.resource_type in ("script", "xhr", "fetch"):
                issues.append("허용되지 않은 SSO 호스트: " + str(urlsplit(request.url).hostname))
            route.abort("blockedbyclient")
            return
        try:
            response = context.request.fetch(request, max_redirects=0, timeout=20000)
            if 300 <= response.status < 400 and response.headers.get("location"):
                target = urljoin(request.url, response.headers["location"])
                if (not request.is_navigation_request() or not _allowed(target)
                        or (response.status in (307, 308) and request.method != "GET")):
                    issues.append("지원되지 않은 SSO 이동: " + str(urlsplit(target).hostname))
                    route.abort("blockedbyclient")
                    return
                encoded = json.dumps(target).replace("<", "\\u003c").replace(">", "\\u003e")
                route.fulfill(status=200, content_type="text/html", body=(
                    "<!doctype html><script>location.replace(" + encoded + ")</script>"
                ))
            else:
                route.fulfill(response=response)
        except Exception:
            # Browser errors may contain SSO state or POST bodies: never log them.
            route.abort("failed")
    context.route("**/*", route_request)
    return issues


@contextmanager
def sso_session(username, password):
    session = requests.Session()
    try:
        with sync_playwright() as playwright:
            options = {"headless": True}
            if not os.environ.get("GITHUB_ACTIONS") and Path("/usr/bin/chromium").exists():
                options["executable_path"] = "/usr/bin/chromium"
            proxy = urlsplit(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "")
            if proxy.hostname:
                options["proxy"] = {"server": f"{proxy.scheme}://{proxy.hostname}:{proxy.port or 80}"}
                if proxy.username:
                    options["proxy"]["username"] = unquote(proxy.username)
                    options["proxy"]["password"] = unquote(proxy.password or "")
            browser = playwright.chromium.launch(**options)
            try:
                context = browser.new_context(service_workers="block")
                issues = []
                if proxy.hostname:
                    issues = _verified_proxy_transport(context)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                stage = "Canvas 로그인 페이지"
                try:
                    page.goto(BASE_URL + "/login", wait_until="domcontentloaded", timeout=30000)
                    stage = "통합 로그인 이동"
                    page.get_by_role("link", name="통합 로그인", exact=True).click(timeout=15000)
                    stage = "학교 로그인 입력칸 확인"
                    page.locator("#userId").wait_for(state="visible", timeout=30000)
                    if urlsplit(page.url).hostname != "login.donga.ac.kr":
                        raise CanvasError("학교 통합 로그인 주소가 변경되었습니다")
                    page.locator("#userId").fill(username)
                    page.locator("#pswd").fill(password)
                    stage = "학교 로그인 요청"
                    # The portal localizes its button text in the browser. Its
                    # password field has an official Enter-to-login handler.
                    page.locator("#pswd").press("Enter", timeout=10000)
                    stage = "학교 인증 후 Canvas 복귀"
                    page.wait_for_url(
                        re.compile(r"^https://canvas\.donga\.ac\.kr(?::443)?/"),
                        wait_until="domcontentloaded", timeout=45000,
                    )
                    for cookie in context.cookies(BASE_URL):
                        if cookie["domain"].lstrip(".") != "canvas.donga.ac.kr":
                            continue
                        session.cookies.set(
                            cookie["name"], cookie["value"], domain=cookie["domain"],
                            path=cookie["path"], secure=cookie["secure"],
                        )
                except CanvasError:
                    raise
                except Exception:
                    raise CanvasError(
                        f"학교 통합 로그인 미완료 ({stage}; {urlsplit(page.url).hostname}). "
                        + (issues[-1] if issues else "계정 정보나 추가 인증 여부를 확인하세요")
                    ) from None
            finally:
                browser.close()
        # A redirect alone is not proof of authentication.
        user, _ = CanvasClient(session)._get("/api/v1/users/self/profile")
        if not isinstance(user, dict) or not user.get("id"):
            raise CanvasError("Canvas 로그인 후 사용자 확인에 실패했습니다")
        yield session
    finally:
        session.close()
