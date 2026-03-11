"""
Signal Bot для POCKET OPTION (лише аналіз, без відкриття угод) з GUI.

Нове:
- Кнопка "Авторизуватися через Google" (без ручного вводу email/password у GUI).
- Автоматичне отримання SSID cookie після входу через браузер.

Примітка:
- Pocket Option не має офіційного Python SDK.
- Для ринкових даних використовується community-клієнт `pocketoptionapi` (опційно).
"""

import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

try:
    from pocketoptionapi.stable_api import PocketOption
except ImportError:
    PocketOption = None

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
    except ImportError:
        EdgeChromiumDriverManager = None
except ImportError:
    webdriver = None
    Service = None
    EdgeChromiumDriverManager = None


DEFAULT_TIMEFRAME_SEC = 300
DEFAULT_CANDLES_LIMIT = 150
DEFAULT_CHECK_INTERVAL_SEC = 20
DEFAULT_API_RETRY_DELAY_SEC = 10

DEFAULT_FOREX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
    "USDCAD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
]

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
    auto_select_best_pair: bool
    timeframe_sec: int
    candles_limit: int
    check_interval_sec: int
    api_retry_delay_sec: int


def build_edge_driver(log: Callable[[str], None]):
    """Створює Edge WebDriver без обов'язкового доступу до мережі."""
    if webdriver is None or Service is None:
        raise ImportError("Для Google-авторизації встановіть: pip install selenium")

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # 1) Пріоритет: EDGE_DRIVER_PATH з оточення (повністю офлайн)
    edge_driver_path = os.getenv("EDGE_DRIVER_PATH", "").strip()
    if edge_driver_path:
        log(f"Спроба запуску EdgeDriver з EDGE_DRIVER_PATH: {edge_driver_path}")
        return webdriver.Edge(service=Service(edge_driver_path), options=options)

    # 2) Пошук msedgedriver у PATH (офлайн)
    path_driver = shutil.which("msedgedriver")
    if path_driver:
        log(f"Знайдено msedgedriver у PATH: {path_driver}")
        return webdriver.Edge(service=Service(path_driver), options=options)

    # 3) Selenium Manager (може спрацювати локально; інколи потребує мережу)
    try:
        log("Пробую Selenium Manager для запуску Edge...")
        return webdriver.Edge(options=options)
    except Exception as error:
        log(f"Selenium Manager не спрацював: {error}")

    # 4) webdriver-manager як останній fallback (потрібна мережа)
    if EdgeChromiumDriverManager is not None:
        log("Пробую webdriver-manager (потрібен інтернет для завантаження драйвера)...")
        driver_path = EdgeChromiumDriverManager().install()
        return webdriver.Edge(service=Service(driver_path), options=options)

    raise RuntimeError(
        "Не вдалося запустити Edge WebDriver офлайн. "
        "Встановіть msedgedriver і додайте в PATH або задайте EDGE_DRIVER_PATH."
    )


def launch_google_auth_and_get_ssid(log: Callable[[str], None]) -> str:
    """Відкриває браузер, дає увійти через Google і забирає SSID cookie автоматично."""
    if webdriver is None:
        raise ImportError(
            "Для Google-авторизації встановіть: pip install selenium"
        )

    log("Запуск браузера для Google-авторизації...")

    driver = build_edge_driver(log)
    driver.maximize_window()

    try:
        driver.get("https://pocketoption.com/en/login/")
        log("Відкрито сторінку логіну Pocket Option.")

        # Працюємо з кількома можливими селекторами кнопки Google
        google_selectors = [
            "button[data-provider='google']",
            "a[data-provider='google']",
            "button.google",
            "a.google",
            "//*[contains(text(), 'Google')]",
            "//*[contains(text(), 'google')]",
        ]

        clicked = False
        for selector in google_selectors:
            try:
                if selector.startswith("//"):
                    element = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                else:
                    element = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                element.click()
                clicked = True
                log("Натиснуто кнопку входу через Google.")
                break
            except Exception:
                continue

        if not clicked:
            log("Не знайдено кнопку Google автоматично. Завершіть вхід вручну у відкритому браузері.")

        # Чекаємо, поки з'явиться ssid cookie після успішного входу
        log("Очікування завершення входу (до 180 сек)...")
        deadline = time.time() + 180
        while time.time() < deadline:
            for cookie in driver.get_cookies():
                name = cookie.get("name", "").lower()
                if name in {"ssid", "session", "sessionid"} and cookie.get("value"):
                    ssid = cookie["value"]
                    log("Google-авторизація успішна, SSID отримано автоматично.")
                    return ssid
            time.sleep(1)

        raise TimeoutError("Не вдалося отримати SSID cookie після Google-авторизації.")
    finally:
        driver.quit()


def create_pocketoption_client(config: BotConfig) -> Any:
    """Створює клієнт Pocket Option з password/google режимом."""
    if PocketOption is None:
        raise ImportError(
            "Модуль pocketoptionapi не знайдено. Встановіть його з GitHub-репозиторію бібліотеки."
        )

    method = config.auth_method.lower().strip()
    if method == "password":
        if not config.email or not config.password:
            raise ValueError("Для password-авторизації потрібні email + password.")
        client = PocketOption(config.email, config.password)
    elif method == "google":
        if not config.google_ssid:
            raise ValueError("Спочатку натисніть кнопку Google-авторизації, щоб отримати SSID.")
        try:
            client = PocketOption(config.google_ssid)
        except TypeError:
            try:
                client = PocketOption(ssid=config.google_ssid)
            except TypeError:
                client = PocketOption("", "", config.google_ssid)
    else:
        raise ValueError("Невідомий метод авторизації.")

    if not client.connect():
        raise ConnectionError("Не вдалося підключитися до Pocket Option.")
    return client


def fetch_ohlc_dataframe(client: Any, symbol: str, timeframe_sec: int, limit: int) -> pd.DataFrame:
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


def analyze_pairs_profitability(client: Any, pairs: list[str], timeframe_sec: int, limit: int, log: Callable[[str], None]) -> list[dict]:
    report = []
    log("Аналіз прибутковості пар...")
    for pair in pairs:
        try:
            df = fetch_ohlc_dataframe(client, pair, timeframe_sec, limit)
            profit = calculate_profitability_percent(df)
            report.append({"symbol": pair, "profit_pct": profit})
            log(f"- {pair}: {profit:+.2f}%")
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

    prev_c = df.iloc[-2]
    curr_c = df.iloc[-1]

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
    log("Підключення до Pocket Option успішне.")

    report = analyze_pairs_profitability(client, config.pairs, config.timeframe_sec, config.candles_limit, log)
    if not report:
        raise RuntimeError("Не вдалося отримати дані по жодній парі.")

    selected_pair = report[0]["symbol"]
    log(f"Пара для моніторингу: {selected_pair}")

    last_signal_ts: Optional[pd.Timestamp] = None
    last_signal_type: Optional[str] = None

    while not stop_event.is_set():
        try:
            df = fetch_ohlc_dataframe(client, selected_pair, config.timeframe_sec, config.candles_limit)
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
                f"[{now_local}] {selected_pair} | Candle: {ts.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
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
        self.root.title("Pocket Option Signal Bot")
        self.root.geometry("950x680")

        self.stop_event = threading.Event()
        self.bot_thread: Optional[threading.Thread] = None
        self.google_ssid_value = ""

        self._build_form()

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Метод авторизації:").grid(row=0, column=0, sticky="w")
        self.auth_method_var = tk.StringVar(value="google")
        ttk.Combobox(
            frame, textvariable=self.auth_method_var,
            values=["google", "password"], state="readonly"
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Button(
            frame,
            text="Авторизуватися через Google",
            command=self.google_auth_click,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Статус Google SSID:").grid(row=2, column=0, sticky="w")
        self.google_status_var = tk.StringVar(value="не отримано")
        ttk.Label(frame, textvariable=self.google_status_var).grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="Email (для password-режиму):").grid(row=3, column=0, sticky="w")
        self.email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Password (для password-режиму):").grid(row=4, column=0, sticky="w")
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
        def worker() -> None:
            try:
                ssid = launch_google_auth_and_get_ssid(self.log)
                self.google_ssid_value = ssid
                self.root.after(0, lambda: self.google_status_var.set("отримано ✅"))
            except Exception as error:
                self.log(f"[ПОМИЛКА GOOGLE AUTH] {error}")
                self.root.after(0, lambda: self.google_status_var.set("помилка ❌"))

        threading.Thread(target=worker, daemon=True).start()

    def _build_config(self) -> BotConfig:
        pairs = [x.strip().upper() for x in self.pairs_var.get().split(",") if x.strip()]
        if not pairs:
            raise ValueError("Вкажіть хоча б одну валютну пару.")

        return BotConfig(
            auth_method=self.auth_method_var.get().strip().lower(),
            email=self.email_var.get().strip(),
            password=self.password_var.get(),
            google_ssid=self.google_ssid_value,
            pairs=pairs,
            auto_select_best_pair=True,
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
# 1) pip install pandas selenium
# 2) Для ринкових даних також встановіть pocketoptionapi (з GitHub-джерела бібліотеки).
# 3) Переконайтесь, що встановлено Microsoft Edge і msedgedriver (додайте в PATH або EDGE_DRIVER_PATH).
# 4) Опційно для авто-завантаження драйвера: pip install webdriver-manager
# 5) python signal_bot_binance.py
# 6) Натисніть "Авторизуватися через Google" — SSID підтягнеться автоматично.
