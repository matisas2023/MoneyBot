import os
import shutil
import subprocess
import time
from typing import Callable

try:
    from selenium import webdriver
    from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
    except ImportError:
        EdgeChromiumDriverManager = None
except ImportError:
    webdriver = None
    Service = None
    EdgeChromiumDriverManager = None
    InvalidSessionIdException = Exception
    WebDriverException = Exception


def build_edge_driver(log: Callable[[str], None]):
    if webdriver is None or Service is None:
        raise ImportError("Встановіть selenium: py -m pip install selenium")

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

    edge_driver_path = os.getenv("EDGE_DRIVER_PATH", "").strip()
    if edge_driver_path:
        return webdriver.Edge(service=Service(edge_driver_path, log_output=subprocess.DEVNULL), options=options)

    path_driver = shutil.which("msedgedriver")
    if path_driver:
        return webdriver.Edge(service=Service(path_driver, log_output=subprocess.DEVNULL), options=options)

    try:
        log("Пробую Selenium Manager для запуску Edge...")
        return webdriver.Edge(options=options)
    except Exception:
        if EdgeChromiumDriverManager is not None:
            log("Пробую webdriver-manager для запуску Edge...")
            path = EdgeChromiumDriverManager().install()
            return webdriver.Edge(service=Service(path, log_output=subprocess.DEVNULL), options=options)
        raise


def extract_session_token_from_cookies(cookies: list[dict]) -> str | None:
    for cookie in cookies:
        name = str(cookie.get("name", "")).lower()
        if name in {"ssid", "session", "sessionid"}:
            return str(cookie.get("value", "")).strip() or None
    return None


def launch_google_auth_and_get_ssid(log: Callable[[str], None]) -> str:
    driver = build_edge_driver(log)
    try:
        driver.get("https://pocketoption.com/en/login/")
        selectors = [
            "button[data-test='google-login']",
            "button[data-test='google']",
            "button.google",
            "//button[contains(.,'Google')]",
            "//a[contains(.,'Google')]",
        ]
        for selector in selectors:
            try:
                if selector.startswith("//"):
                    el = WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.XPATH, selector)))
                else:
                    el = WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                break
            except Exception:
                continue

        log("Очікування завершення входу (до 240 сек)...")
        deadline = time.time() + 240
        phase_last_log = 0.0
        while time.time() < deadline:
            try:
                token = extract_session_token_from_cookies(driver.get_cookies())
                if token:
                    log("Авторизація підтверджена, сесійний токен отримано.")
                    return token
                if time.time() - phase_last_log >= 10:
                    log("Очікування авторизації в браузері...")
                    phase_last_log = time.time()
            except InvalidSessionIdException:
                raise RuntimeError("Сесія Edge закрита під час авторизації.")
            except WebDriverException as error:
                raise RuntimeError(f"Помилка WebDriver: {error}")
            time.sleep(1)
        raise TimeoutError("Не вдалося отримати SSID після Google-входу.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
