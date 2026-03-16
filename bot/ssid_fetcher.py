from __future__ import annotations

import time
from typing import Callable, Literal

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions


def _extract_ssid_from_cookies(cookies: list[dict]) -> str | None:
    names = {"ssid", "session", "sessionid", "connect.sid", "ci_session"}
    for cookie in cookies:
        name = str(cookie.get("name", "")).lower()
        value = str(cookie.get("value", "")).strip()
        if value and (name in names or "sid" in name or "session" in name):
            return value
    return None


def _extract_ssid_from_storage(driver) -> str | None:
    script = """
const out = [];
for (let i = 0; i < localStorage.length; i++) {
  const key = localStorage.key(i);
  out.push([key, localStorage.getItem(key)]);
}
for (let i = 0; i < sessionStorage.length; i++) {
  const key = sessionStorage.key(i);
  out.push([key, sessionStorage.getItem(key)]);
}
return out;
"""
    try:
        values = driver.execute_script(script)
    except WebDriverException:
        return None

    if not isinstance(values, list):
        return None

    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        key = str(item[0]).lower()
        val = str(item[1] or "").strip()
        if not val:
            continue
        if "ssid" in key or "session" in key or "sid" in key:
            return val
    return None


def _build_driver(browser: Literal["edge", "chrome"] = "edge", headless: bool = False):
    if browser == "chrome":
        options = ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        return webdriver.Chrome(options=options)

    options = EdgeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Edge(options=options)


def get_ssid(
    timeout: int = 240,
    browser: Literal["edge", "chrome"] = "edge",
    headless: bool = False,
    log: Callable[[str], None] | None = None,
) -> str:
    """
    Opens browser, waits for login, retrieves PocketOption SSID.
    """
    logger = log or print

    logger("[INFO] Launching browser for PocketOption login...")
    driver = _build_driver(browser=browser, headless=headless)

    try:
        driver.get("https://pocketoption.com")
        logger(f"[INFO] Waiting for user authentication ({timeout}s)...")
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                current_url = driver.current_url.lower()
                login_detected = any(
                    marker in current_url for marker in ("/cabinet", "/trade", "/trading", "/quick-high-low")
                )

                cookie_ssid = _extract_ssid_from_cookies(driver.get_cookies())
                storage_ssid = _extract_ssid_from_storage(driver)
                ssid = cookie_ssid or storage_ssid

                if login_detected and ssid:
                    logger("[INFO] Login detected.")
                    logger("[INFO] Session SSID captured.")
                    return ssid

                if ssid:
                    logger("[INFO] Session SSID captured.")
                    return ssid

            except InvalidSessionIdException as exc:
                raise RuntimeError("Browser session was closed before SSID retrieval") from exc
            except WebDriverException:
                # transient page state issues while user logs in
                pass

            time.sleep(1)

        raise TimeoutError("[ERROR] Could not retrieve SSID within timeout.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
