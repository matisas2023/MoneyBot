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
import threading
import time
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


def patch_logger_warn_compat(target: Any) -> None:
    """Додає alias warn->warning для об'єктів logger у сторонніх бібліотеках."""
    if target is None:
        return

    def _patch_obj(obj: Any) -> None:
        if obj is None:
            return
        if hasattr(obj, "warning") and not hasattr(obj, "warn"):
            # 1) пробуємо патчити екземпляр
            try:
                setattr(obj, "warn", obj.warning)
                return
            except Exception:
                pass

            # 2) fallback: патчимо клас логера
            try:
                cls = obj.__class__
                if not hasattr(cls, "warn") and hasattr(cls, "warning"):
                    setattr(cls, "warn", cls.warning)
            except Exception:
                pass

    _patch_obj(target)

    # Якщо target має поле logger
    logger_obj = getattr(target, "logger", None)
    _patch_obj(logger_obj)

# =========================
# API import: BinaryOptionsToolsV2
# =========================
try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
except ImportError:
    print("Library BinaryOptionsToolsV2 not installed")
    print("Run: pip install binaryoptionstoolsv2")
    raise SystemExit()

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
                    result = fn()
                except AttributeError as error:
                    if "warn" in str(error).lower():
                        patch_logger_warn_compat(self.raw_client)
                        result = fn()
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
                return fn(symbol, timeframe_sec, start_time, end_time)
            except AttributeError as error:
                if "warn" in str(error).lower():
                    patch_logger_warn_compat(self.raw_client)
                    return fn(symbol, timeframe_sec, start_time, end_time)
                raise
            except TypeError:
                try:
                    return fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                except AttributeError as error:
                    if "warn" in str(error).lower():
                        patch_logger_warn_compat(self.raw_client)
                        return fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
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


def create_pocketoption_client(config: BotConfig) -> PocketOptionDataClient:

    method = config.auth_method.lower().strip()
    if method == "google":
        if not config.google_ssid:
            raise ValueError("Спочатку виконайте Google-авторизацію (отримайте SSID).")
        # можливі сигнатури різних збірок
        try:
            raw_client = PocketOption(ssid=config.google_ssid)
        except TypeError:
            try:
                raw_client = PocketOption(config.google_ssid)
            except TypeError:
                raw_client = PocketOption("", "", config.google_ssid)
    else:
        if not config.email or not config.password:
            raise ValueError("Для password-режиму потрібні email та password.")
        try:
            raw_client = PocketOption(email=config.email, password=config.password)
        except TypeError:
            raw_client = PocketOption(config.email, config.password)

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
            log(f"[ПОМИЛКА API] {error}")
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
                self.log(f"[КРИТИЧНА ПОМИЛКА] {error}")

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
