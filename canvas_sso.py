"""Log in through Donga's normal SSO UI and retain only Canvas session cookies."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from playwright.sync_api import sync_playwright
import requests

from canvas_lms import BASE_URL, CanvasClient, CanvasError


SSO_HOSTS = {
    "canvas.donga.ac.kr", "eclass.donga.ac.kr",
    "dxsso.donga.ac.kr", "login.donga.ac.kr",
}

LOGIN_ERRORS = {
    "9000": "학교 계정 아이디를 찾지 못했습니다",
    "9001": "학교 비밀번호가 일치하지 않습니다. GitHub의 CANVAS_PW를 확인하세요",
    "9002": "학교 포털에서 중복 로그인 확인이 필요합니다",
    "9003": "학교 계정이 차단된 상태입니다",
    "9004": "학교 계정의 접근 권한을 확인해야 합니다",
    "9005": "학교 계정의 로그인 오류 횟수를 초과했습니다",
    "9006": "학교 비밀번호 변경이 필요합니다",
    "9007": "학교 초기 비밀번호 변경이 필요합니다",
    "9008": "학교가 실행 환경의 IP에서 로그인을 제한했습니다",
    "9009": "학교 포털의 개인정보 이용 동의가 필요합니다",
    "9010": "학교 계정의 로그인이 제한됐습니다",
    "9011": "학교 계정의 사용 기한이 만료됐습니다",
    "9012": "학교 포털의 추가 인증이 필요합니다",
}


def _login_error(page):
    try:
        code = page.evaluate("""() => {
            const element = document.querySelector('[x-data="loginFormData"]');
            return element && window.Alpine ? String(Alpine.$data(element).loginErrorCode || '') : '';
        }""")
    except Exception:
        return None
    # Only output known public error codes, never arbitrary page/server text.
    return f"{LOGIN_ERRORS[code]} (학교 오류 {code})" if code in LOGIN_ERRORS else None


def _allowed(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in SSO_HOSTS
            and parts.port in (None, 443) and not parts.username and not parts.password)


def _handle_dialog(page, dialog, replace_existing):
    duplicate = ("이전 로그인을 끊고 강제로 로그인하시겠습니까?" in dialog.message
                 or "Do you want to terminate the previous login and force a login?" in dialog.message)
    if (replace_existing and dialog.type == "confirm" and duplicate
            and urlsplit(page.url).hostname == "login.donga.ac.kr"):
        dialog.accept()
    else:
        dialog.dismiss()


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
def sso_session(username, password, replace_existing=None):
    if replace_existing is None:
        replace_existing = os.environ.get("CANVAS_REPLACE_SESSION", "false").lower() == "true"
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
                page.on("dialog", lambda dialog: _handle_dialog(page, dialog, replace_existing))
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
                    page.wait_for_function("""replaceExisting => {
                        if (location.hostname === 'canvas.donga.ac.kr') return true;
                        const element = document.querySelector('[x-data="loginFormData"]');
                        const code = element && window.Alpine ? String(Alpine.$data(element).loginErrorCode || '') : '';
                        return code && code !== '9100' && code !== '9101'
                            && !(replaceExisting && code === '9002');
                    }""", arg=replace_existing, timeout=45000)
                    if urlsplit(page.url).hostname != "canvas.donga.ac.kr":
                        raise CanvasError(_login_error(page) or "학교 인증을 완료하지 못했습니다")
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
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
                        + (_login_error(page) or (issues[-1] if issues else "계정 정보나 추가 인증 여부를 확인하세요"))
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
