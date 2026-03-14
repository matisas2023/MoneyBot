"""
Signal Bot для Pocket Option (analysis-only) на базі BinaryOptionsToolsV2.

Що змінено:
- Бібліотека для API: BinaryOptionsToolsV2 (замість pocketoptionapi).
- Працює тільки як signal-bot: BUY / SELL / NO SIGNAL, без відкриття угод.
- GUI на Tkinter + Google auth (через SSID cookie з Edge).
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

# Налаштування logging + сумісність зі старим logger.warn
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)
logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]


def patch_loaded_logger_classes_warn_alias() -> None:
    """Патчить warn->warning для класів logger у вже завантажених модулях."""
    for module in list(sys.modules.values()):
        if module is None:
            continue

        for class_name in ("Logger", "LoggerAdapter"):
            logger_cls = getattr(module, class_name, None)
            if isinstance(logger_cls, type) and hasattr(logger_cls, "warning") and not hasattr(logger_cls, "warn"):
                try:
                    setattr(logger_cls, "warn", logger_cls.warning)
                except Exception:
                    pass


def patch_third_party_warn_compat() -> None:
    """Патчить найпоширеніші сторонні логери, де може бути відсутній warn()."""
    patch_loaded_logger_classes_warn_alias()
    # loguru logger
    try:
        from loguru import logger as loguru_logger  # type: ignore
        if hasattr(loguru_logger, "warning") and not hasattr(loguru_logger, "warn"):
            setattr(loguru_logger, "warn", loguru_logger.warning)
    except Exception:
        pass


patch_loaded_logger_classes_warn_alias()
patch_third_party_warn_compat()


def patch_logger_warn_compat(target: Any) -> None:
    """Додає alias warn->warning для logger-об'єктів, у т.ч. вкладених у сторонніх клієнтах."""
    if target is None:
        return

    visited_ids: set[int] = set()
    queue = deque([(target, 0)])
    max_depth = 4

    while queue:
        obj, depth = queue.popleft()
        if obj is None:
            continue
        obj_id = id(obj)
        if obj_id in visited_ids:
            continue
        visited_ids.add(obj_id)

        # 1) патч екземпляра
        if hasattr(obj, "warning") and not hasattr(obj, "warn"):
            try:
                setattr(obj, "warn", obj.warning)
            except Exception:
                pass

        # 2) патч класу екземпляра
        try:
            cls = obj.__class__
            if hasattr(cls, "warning") and not hasattr(cls, "warn"):
                try:
                    setattr(cls, "warn", cls.warning)
                except Exception:
                    pass
        except Exception:
            pass

        if depth >= max_depth:
            continue

        # 3) обхід вкладених атрибутів об'єкта
        try:
            attrs = vars(obj)
        except Exception:
            attrs = None

        if isinstance(attrs, dict):
            for value in attrs.values():
                # не занурюємось у примітиви
                if isinstance(value, (str, bytes, int, float, bool, type(None))):
                    continue
                queue.append((value, depth + 1))


# =========================
# API import: BinaryOptionsToolsV2
# =========================
try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
    from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
except ImportError:
    print("Library BinaryOptionsToolsV2 not installed")
    print("Run: pip install binaryoptionstoolsv2")
    raise SystemExit()


def patch_binaryoptionstoolsv2_warn_alias() -> None:
    """Патчить logger.warn для внутрішніх об'єктів BinaryOptionsToolsV2."""
    try:
        # 1) module-level logger у asynchronous.py
        module_logger = getattr(po_async, "logger", None)
        if module_logger is not None and hasattr(module_logger, "warning") and not hasattr(module_logger, "warn"):
            setattr(module_logger, "warn", module_logger.warning)

        # 1.1) патч класу логера, який повертає logging.getLogger()
        async_logging = getattr(po_async, "logging", None)
        if async_logging is not None:
            logger_cls = getattr(async_logging, "Logger", None)
            if isinstance(logger_cls, type) and hasattr(logger_cls, "warning") and not hasattr(logger_cls, "warn"):
                setattr(logger_cls, "warn", logger_cls.warning)
            get_logger_class = getattr(async_logging, "getLoggerClass", None)
            if callable(get_logger_class):
                runtime_cls = get_logger_class()
                if hasattr(runtime_cls, "warning") and not hasattr(runtime_cls, "warn"):
                    setattr(runtime_cls, "warn", runtime_cls.warning)
    except Exception:
        pass

    try:
        # 2) класи Logger всередині модуля BinaryOptionsToolsV2.pocketoption.asynchronous
        for value in vars(po_async).values():
            if isinstance(value, type) and "Logger" in value.__name__:
                if hasattr(value, "warning") and not hasattr(value, "warn"):
                    setattr(value, "warn", value.warning)
    except Exception:
        pass

    try:
        # 3) loguru class-level patch (частий кейс)
        import loguru._logger as loguru_logger_module  # type: ignore
        loguru_cls = getattr(loguru_logger_module, "Logger", None)
        if isinstance(loguru_cls, type) and hasattr(loguru_cls, "warning") and not hasattr(loguru_cls, "warn"):
            setattr(loguru_cls, "warn", loguru_cls.warning)
    except Exception:
        pass

    try:
        # 4) додатково патчимо __init__ PocketOptionAsync, щоб гарантовано застосувати alias перед warn-викликом
        async_cls = getattr(po_async, "PocketOptionAsync", None)
        original_init = getattr(async_cls, "__init__", None) if async_cls is not None else None
        if async_cls is not None and callable(original_init) and not getattr(async_cls, "_warn_patch_wrapped", False):
            def _wrapped_init(self, *args, **kwargs):
                patch_loaded_logger_classes_warn_alias()
                patch_third_party_warn_compat()
                return original_init(self, *args, **kwargs)

            setattr(async_cls, "__init__", _wrapped_init)
            setattr(async_cls, "_warn_patch_wrapped", True)
    except Exception:
        pass


patch_binaryoptionstoolsv2_warn_alias()


# Мінімальний приклад підключення:
# client = PocketOption(ssid="YOUR_SESSION_ID")

BOTSV2_INSTALL_HELP = (
    "Library BinaryOptionsToolsV2 not installed.\n"
    "Run: pip install binaryoptionstoolsv2"
)

# =========================
# Selenium imports (Edge)
# =========================
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
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


DEFAULT_TIMEFRAME_SEC = 300
DEFAULT_CANDLES_LIMIT = 150
DEFAULT_CHECK_INTERVAL_SEC = 20
DEFAULT_API_RETRY_DELAY_SEC = 10

DEFAULT_FOREX_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14


DETAILED_LOGGING = True


def build_warn_diagnostics(target: Any) -> str:
    """Формує діагностику для помилки logger.warn у сторонніх об'єктах."""
    lines = []
    try:
        lines.append(f"target_type={type(target)}")
        cls = target.__class__
        lines.append(f"target_class={cls.__module__}.{cls.__name__}")
        lines.append(f"target_has_warning={hasattr(target, 'warning')}")
        lines.append(f"target_has_warn={hasattr(target, 'warn')}")
    except Exception as diag_error:
        lines.append(f"target_diag_error={diag_error}")

    try:
        logger_obj = getattr(target, 'logger', None)
        if logger_obj is not None:
            lcls = logger_obj.__class__
            lines.append(f"logger_class={lcls.__module__}.{lcls.__name__}")
            lines.append(f"logger_has_warning={hasattr(logger_obj, 'warning')}")
            lines.append(f"logger_has_warn={hasattr(logger_obj, 'warn')}")
    except Exception as diag_error:
        lines.append(f"logger_diag_error={diag_error}")

    return ' | '.join(lines)


def debug_warn_logger_state(logger_obj: Any, log: Optional[Callable[[str], None]] = None) -> None:
    """Debug: друкує тип logger та наявність warn/warning."""
    msg = (
        f"[WARN-DEBUG] logger_type={type(logger_obj)} "
        f"has_warn={hasattr(logger_obj, 'warn')} "
        f"has_warning={hasattr(logger_obj, 'warning')}"
    )
    if callable(log):
        log(msg)
    else:
        print(msg)


def log_exception_with_trace(log: Callable[[str], None], prefix: str, error: Exception) -> None:
    log(f"{prefix} {error}")
    if DETAILED_LOGGING:
        tb = traceback.format_exc()
        for line in tb.rstrip().splitlines():
            log(f"[TRACE] {line}")


@dataclass
class BotConfig:
    auth_method: str
    email: str
    password: str
    google_ssid: str
    pairs: list[str]
    timeframe_sec: int
    candles_limit: int
    check_interval_sec: int
    api_retry_delay_sec: int


class PocketOptionDataClient:
    """Уніфікований адаптер над BinaryOptionsToolsV2 для різних форків/сигнатур."""

    def __init__(self, raw_client: Any):
        self.raw_client = raw_client

    def connect(self) -> bool:
        for name in ("connect", "login", "start"):
            fn = getattr(self.raw_client, name, None)
            if callable(fn):
                try:
                    patch_loaded_logger_classes_warn_alias()
                    result = fn()
                except AttributeError as error:
                    if "warn" in str(error).lower():
                        patch_logger_warn_compat(self.raw_client)
                        patch_loaded_logger_classes_warn_alias()
                        try:
                            result = fn()
                        except Exception as retry_error:
                            diag = build_warn_diagnostics(self.raw_client)
                            raise RuntimeError(f"warn_retry_connect_failed: {retry_error} | {diag}") from retry_error
                    else:
                        raise
                return True if result is None else bool(result)
        return True

    def get_candles(self, symbol: str, timeframe_sec: int, start_time: int, end_time: int):
        # Найпоширеніші варіанти методу в різних версіях/форках
        method_candidates = ["get_candles", "candles", "fetch_candles", "get_history"]
        for name in method_candidates:
            fn = getattr(self.raw_client, name, None)
            if not callable(fn):
                continue
            try:
                patch_loaded_logger_classes_warn_alias()
                return fn(symbol, timeframe_sec, start_time, end_time)
            except AttributeError as error:
                if "warn" in str(error).lower():
                    patch_logger_warn_compat(self.raw_client)
                    patch_loaded_logger_classes_warn_alias()
                    try:
                        return fn(symbol, timeframe_sec, start_time, end_time)
                    except Exception as retry_error:
                        diag = build_warn_diagnostics(self.raw_client)
                        raise RuntimeError(f"warn_retry_candles_positional_failed: {retry_error} | {diag}") from retry_error
                raise
            except TypeError:
                try:
                    patch_loaded_logger_classes_warn_alias()
                    return fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                except AttributeError as error:
                    if "warn" in str(error).lower():
                        patch_logger_warn_compat(self.raw_client)
                        patch_loaded_logger_classes_warn_alias()
                        try:
                            return fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                        except Exception as retry_error:
                            diag = build_warn_diagnostics(self.raw_client)
                            raise RuntimeError(f"warn_retry_candles_kwargs_failed: {retry_error} | {diag}") from retry_error
                    raise
                except TypeError:
                    continue
        raise AttributeError("У client не знайдено сумісний метод отримання свічок.")


def build_edge_driver(log: Callable[[str], None]):
    if webdriver is None or Service is None:
        raise ImportError("Для Google-авторизації встановіть: py -m pip install selenium")

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
        pass

    if EdgeChromiumDriverManager is not None:
        driver_path = EdgeChromiumDriverManager().install()
        return webdriver.Edge(service=Service(driver_path, log_output=subprocess.DEVNULL), options=options)

    raise RuntimeError("Не вдалося запустити Edge WebDriver. Додайте msedgedriver в PATH або EDGE_DRIVER_PATH.")


def extract_session_token_from_cookies(cookies: list[dict]) -> Optional[str]:
    for key in ("ssid", "session", "sessionid", "connect.sid", "ci_session"):
        for cookie in cookies:
            if cookie.get("name", "").lower() == key and cookie.get("value"):
                return cookie["value"]
    for cookie in cookies:
        name = cookie.get("name", "").lower()
        if cookie.get("value") and ("sid" in name or "session" in name):
            return cookie.get("value")
    return None


def launch_google_auth_and_get_ssid(log: Callable[[str], None]) -> str:
    driver = build_edge_driver(log)
    driver.maximize_window()
    try:
        driver.get("https://pocketoption.com/en/login/")
        selectors = [
            "button[data-provider='google']", "a[data-provider='google']", "a[href*='google']",
            "//*[contains(translate(text(),'GOOGLE','google'),'google')]",
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

                now = time.time()
                if now - phase_last_log >= 10:
                    log("Очікування авторизації в браузері...")
                    phase_last_log = now
            except InvalidSessionIdException:
                raise RuntimeError("Сесія Edge закрита під час авторизації.")
            except WebDriverException as error:
                raise RuntimeError(f"Помилка WebDriver: {error}")
            time.sleep(1)

        raise TimeoutError("Не вдалося отримати сесію після Google-входу.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass



def construct_pocketoption_with_warn_retry(*args, **kwargs):
    """Створює PocketOption з повторною спробою після патчу warn-сумісності."""
    patch_binaryoptionstoolsv2_warn_alias()
    debug_warn_logger_state(getattr(po_async, "logger", None))
    try:
        return PocketOption(*args, **kwargs)
    except AttributeError as error:
        if "warn" in str(error).lower():
            patch_third_party_warn_compat()
            patch_binaryoptionstoolsv2_warn_alias()
            debug_warn_logger_state(getattr(po_async, "logger", None))
            return PocketOption(*args, **kwargs)
        raise


def create_pocketoption_client(config: BotConfig) -> PocketOptionDataClient:

    method = config.auth_method.lower().strip()
    if method == "google":
        if not config.google_ssid:
            raise ValueError("Спочатку виконайте Google-авторизацію (отримайте SSID).")
        # можливі сигнатури різних збірок
        try:
            raw_client = construct_pocketoption_with_warn_retry(ssid=config.google_ssid)
        except TypeError:
            try:
                raw_client = construct_pocketoption_with_warn_retry(config.google_ssid)
            except TypeError:
                raw_client = construct_pocketoption_with_warn_retry("", "", config.google_ssid)
    else:
        # UX-fallback: якщо SSID уже отримано, використовуємо його навіть коли випадково обрано password
        if config.google_ssid:
            logger.warning(
                "Обрано '%s' режим, але BinaryOptionsToolsV2 очікує SSID. "
                "Використовую отриманий SSID автоматично.",
                method,
            )
            try:
                raw_client = construct_pocketoption_with_warn_retry(ssid=config.google_ssid)
            except TypeError:
                try:
                    raw_client = construct_pocketoption_with_warn_retry(config.google_ssid)
                except TypeError:
                    raw_client = construct_pocketoption_with_warn_retry("", "", config.google_ssid)
        else:
            raise ValueError(
                "Для BinaryOptionsToolsV2 у цій збірці підтримується авторизація через SSID. "
                "Оберіть режим 'google' і отримайте SSID кнопкою авторизації."
            )

    print("PocketOption client initialized")
    patch_logger_warn_compat(raw_client)
    client = PocketOptionDataClient(raw_client)
    patch_logger_warn_compat(client)
    connected = client.connect()
    patch_logger_warn_compat(raw_client)
    patch_logger_warn_compat(client)
    if not connected:
        raise ConnectionError("Не вдалося підключитися до Pocket Option через BinaryOptionsToolsV2.")
    return client


def fetch_ohlc_dataframe(client: PocketOptionDataClient, symbol: str, timeframe_sec: int, limit: int) -> pd.DataFrame:
    end_time = int(time.time())
    start_time = end_time - timeframe_sec * limit
    candles = client.get_candles(symbol, timeframe_sec, start_time, end_time)
    if not candles:
        raise ValueError(f"Не отримано свічок для {symbol}.")

    df = pd.DataFrame(candles).rename(columns={
        "from": "timestamp", "time": "timestamp", "t": "timestamp",
        "o": "open", "h": "high", "l": "low", "c": "close",
    })
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"Некоректний формат свічок: {list(df.columns)}")

    df = df[["timestamp", "open", "high", "low", "close"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna().sort_values("timestamp").reset_index(drop=True)


def calculate_profitability_percent(df: pd.DataFrame) -> float:
    if df.empty:
        return float("-inf")
    first_close = float(df.iloc[0]["close"])
    last_close = float(df.iloc[-1]["close"])
    if first_close == 0:
        return float("-inf")
    return ((last_close - first_close) / first_close) * 100


def analyze_pairs_profitability(client: PocketOptionDataClient, pairs: list[str], timeframe_sec: int, limit: int, log: Callable[[str], None]) -> list[dict]:
    report = []
    log("Аналіз прибутковості пар...")
    for pair in pairs:
        try:
            df = fetch_ohlc_dataframe(client, pair, timeframe_sec, limit)
            p = calculate_profitability_percent(df)
            report.append({"symbol": pair, "profit_pct": p})
            log(f"- {pair}: {p:+.2f}%")
        except Exception as error:
            log(f"- {pair}: помилка ({error})")
    report.sort(key=lambda x: x["profit_pct"], reverse=True)
    return report


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema9"] = out["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    out["ema21"] = out["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    out["rsi"] = 100 - (100 / (1 + rs))
    return out


def detect_signal(df: pd.DataFrame) -> str:
    if len(df) < RSI_PERIOD + 2:
        return "NO SIGNAL"
    prev_c, curr_c = df.iloc[-2], df.iloc[-1]
    if pd.isna(curr_c["rsi"]):
        return "NO SIGNAL"

    buy = (
        prev_c["ema9"] <= prev_c["ema21"]
        and curr_c["ema9"] > curr_c["ema21"]
        and 45 <= curr_c["rsi"] <= 70
        and curr_c["close"] > curr_c["ema21"]
    )
    sell = (
        prev_c["ema9"] >= prev_c["ema21"]
        and curr_c["ema9"] < curr_c["ema21"]
        and 30 <= curr_c["rsi"] <= 55
        and curr_c["close"] < curr_c["ema21"]
    )
    if buy:
        return "BUY"
    if sell:
        return "SELL"
    return "NO SIGNAL"


def run_signal_bot(config: BotConfig, stop_event: threading.Event, log: Callable[[str], None]) -> None:
    client = create_pocketoption_client(config)
    report = analyze_pairs_profitability(client, config.pairs, config.timeframe_sec, config.candles_limit, log)
    if not report:
        raise RuntimeError("Не вдалося отримати дані по парах.")
    symbol = report[0]["symbol"]
    log(f"Пара для моніторингу: {symbol}")

    last_signal_ts = None
    last_signal_type = None

    while not stop_event.is_set():
        try:
            df = fetch_ohlc_dataframe(client, symbol, config.timeframe_sec, config.candles_limit)
            df = calculate_indicators(df)
            signal = detect_signal(df)
            curr = df.iloc[-1]
            ts = curr["timestamp"]

            duplicate = signal in ("BUY", "SELL") and ts == last_signal_ts and signal == last_signal_type
            if signal in ("BUY", "SELL") and not duplicate:
                last_signal_ts = ts
                last_signal_type = signal

            now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log(
                f"[{now_local}] {symbol} | Candle: {ts.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                f"Close: {float(curr['close']):.6f} | EMA9: {float(curr['ema9']):.6f} | "
                f"EMA21: {float(curr['ema21']):.6f} | RSI: {float(curr['rsi']):.2f} | "
                f"Signal: {signal}{' (дублікат пропущено)' if duplicate else ''}"
            )
            stop_event.wait(config.check_interval_sec)
        except Exception as error:
            log_exception_with_trace(log, "[ПОМИЛКА API]", error)
            stop_event.wait(config.api_retry_delay_sec)


class SignalBotGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pocket Option Signal Bot (BinaryOptionsToolsV2)")
        self.root.geometry("950x680")

        self.stop_event = threading.Event()
        self.bot_thread: Optional[threading.Thread] = None
        self.google_ssid_value = ""
        self.google_auth_in_progress = False

        self._build_form()

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Метод авторизації:").grid(row=0, column=0, sticky="w")
        self.auth_method_var = tk.StringVar(value="google")
        ttk.Combobox(frame, textvariable=self.auth_method_var, values=["google", "password"], state="readonly").grid(
            row=0, column=1, sticky="ew", padx=6, pady=4
        )

        self.google_auth_button = ttk.Button(frame, text="Авторизуватися через Google", command=self.google_auth_click)
        self.google_auth_button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Статус Google SSID:").grid(row=2, column=0, sticky="w")
        self.google_status_var = tk.StringVar(value="не отримано")
        ttk.Label(frame, textvariable=self.google_status_var).grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="Email (для password):").grid(row=3, column=0, sticky="w")
        self.email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Password (для password):").grid(row=4, column=0, sticky="w")
        self.password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.password_var, show="*").grid(row=4, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Валютні пари (через кому):").grid(row=5, column=0, sticky="w")
        self.pairs_var = tk.StringVar(value=", ".join(DEFAULT_FOREX_PAIRS))
        ttk.Entry(frame, textvariable=self.pairs_var).grid(row=5, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Таймфрейм (сек):").grid(row=6, column=0, sticky="w")
        self.timeframe_var = tk.StringVar(value=str(DEFAULT_TIMEFRAME_SEC))
        ttk.Entry(frame, textvariable=self.timeframe_var).grid(row=6, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Кількість свічок:").grid(row=7, column=0, sticky="w")
        self.limit_var = tk.StringVar(value=str(DEFAULT_CANDLES_LIMIT))
        ttk.Entry(frame, textvariable=self.limit_var).grid(row=7, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Інтервал перевірки (сек):").grid(row=8, column=0, sticky="w")
        self.check_var = tk.StringVar(value=str(DEFAULT_CHECK_INTERVAL_SEC))
        ttk.Entry(frame, textvariable=self.check_var).grid(row=8, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Пауза після помилки (сек):").grid(row=9, column=0, sticky="w")
        self.retry_var = tk.StringVar(value=str(DEFAULT_API_RETRY_DELAY_SEC))
        ttk.Entry(frame, textvariable=self.retry_var).grid(row=9, column=1, sticky="ew", padx=6, pady=4)

        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(buttons, text="Старт", command=self.start_bot).pack(side="left", padx=4)
        ttk.Button(buttons, text="Стоп", command=self.stop_bot).pack(side="left", padx=4)

        self.log_text = tk.Text(frame, height=22, wrap="word")
        self.log_text.grid(row=11, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(11, weight=1)

    def log(self, text: str) -> None:
        self.root.after(0, lambda: (self.log_text.insert("end", text + "\n"), self.log_text.see("end")))

    def google_auth_click(self) -> None:
        if self.google_auth_in_progress:
            self.log("Google-авторизація вже виконується.")
            return

        self.google_auth_in_progress = True
        self.google_auth_button.configure(state="disabled")
        self.google_status_var.set("в процесі...")

        def finish_ui() -> None:
            self.google_auth_in_progress = False
            self.google_auth_button.configure(state="normal")

        def worker() -> None:
            try:
                ssid = launch_google_auth_and_get_ssid(self.log)
                self.google_ssid_value = ssid
                self.root.after(0, lambda: self.google_status_var.set("отримано ✅"))
                self.root.after(0, lambda: self.auth_method_var.set("google"))
            except Exception as error:
                self.log(f"[ПОМИЛКА GOOGLE AUTH] {error}")
                self.root.after(0, lambda: self.google_status_var.set("помилка ❌"))
            finally:
                self.root.after(0, finish_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _build_config(self) -> BotConfig:
        pairs = [x.strip().upper() for x in self.pairs_var.get().split(",") if x.strip()]
        if not pairs:
            raise ValueError("Вкажіть хоча б одну пару.")

        return BotConfig(
            auth_method=self.auth_method_var.get().strip().lower(),
            email=self.email_var.get().strip(),
            password=self.password_var.get(),
            google_ssid=self.google_ssid_value,
            pairs=pairs,
            timeframe_sec=int(self.timeframe_var.get()),
            candles_limit=int(self.limit_var.get()),
            check_interval_sec=int(self.check_var.get()),
            api_retry_delay_sec=int(self.retry_var.get()),
        )

    def start_bot(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            messagebox.showinfo("Інфо", "Бот уже запущений.")
            return

        try:
            config = self._build_config()
        except Exception as error:
            messagebox.showerror("Помилка конфігурації", str(error))
            return

        self.stop_event.clear()

        def runner() -> None:
            try:
                run_signal_bot(config, self.stop_event, self.log)
            except ImportError as error:
                self.log(f"[ВІДСУТНЯ ЗАЛЕЖНІСТЬ] {error}")
                err_text = str(error)
                self.root.after(0, lambda e=err_text: messagebox.showerror("Відсутня залежність", e))
            except Exception as error:
                if "warn" in str(error).lower() and "logger" in str(error).lower():
                    self.log("Виявлено несумісний logger.warn, застосовую сумісність і повторюю запуск...")
                    patch_third_party_warn_compat()
                    try:
                        run_signal_bot(config, self.stop_event, self.log)
                        return
                    except Exception as retry_error:
                        log_exception_with_trace(self.log, "[КРИТИЧНА ПОМИЛКА ПІСЛЯ RETRY]", retry_error)
                log_exception_with_trace(self.log, "[КРИТИЧНА ПОМИЛКА]", error)

        self.bot_thread = threading.Thread(target=runner, daemon=True)
        self.bot_thread.start()
        self.log("Бот запущено.")

    def stop_bot(self) -> None:
        self.stop_event.set()
        self.log("Зупинка запитана.")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SignalBotGUI().run()


if __name__ == "__main__":
    main()

# Інструкція запуску:
# 1) py -m pip install pandas selenium
# 2) Встановіть API: py -m pip install binaryoptionstoolsv2
# 3) Переконайтесь, що встановлено Microsoft Edge і msedgedriver (PATH або EDGE_DRIVER_PATH)
# 4) Опційно: py -m pip install webdriver-manager
# 5) python signal_bot_binance.py
