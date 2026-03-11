"""
Signal Bot для POCKET OPTION (лише аналіз, без відкриття угод) з GUI.

Функціонал:
- Авторизація через Email/Password або Google-session (SSID).
- Завантаження OHLC для валютних пар Pocket Option.
- Аналіз прибутковості списку пар перед моніторингом.
- Розрахунок EMA(9), EMA(21), RSI(14) без TA-Lib.
- Сигнали BUY / SELL / NO SIGNAL.
- Захист від дублювання сигналів на тій самій свічці.
- Графічна оболонка (Tkinter) для запуску/зупинки бота.

Увага:
Pocket Option не має офіційного публічного Python SDK.
Скрипт орієнтований на community-бібліотеку `pocketoptionapi`.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

try:
    from pocketoptionapi.stable_api import PocketOption
except ImportError:
    PocketOption = None


# =========================
# Константи за замовчуванням
# =========================
DEFAULT_TIMEFRAME_SEC = 300
DEFAULT_CANDLES_LIMIT = 150
DEFAULT_CHECK_INTERVAL_SEC = 20
DEFAULT_API_RETRY_DELAY_SEC = 10

DEFAULT_FOREX_PAIRS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
]

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14


@dataclass
class BotConfig:
    auth_method: str  # "password" | "google"
    email: str
    password: str
    google_ssid: str
    pairs: list[str]
    auto_select_best_pair: bool
    timeframe_sec: int
    candles_limit: int
    check_interval_sec: int
    api_retry_delay_sec: int


# =========================
# Службові функції API
# =========================
def create_pocketoption_client(config: BotConfig) -> Any:
    """Створює клієнт Pocket Option з підтримкою двох способів авторизації."""
    if PocketOption is None:
        raise ImportError("Не знайдено pocketoptionapi. Встановіть: pip install pocketoptionapi")

    auth_method = config.auth_method.lower().strip()

    # Авторизація через Email/Password
    if auth_method == "password":
        if not config.email or not config.password:
            raise ValueError("Для авторизації password потрібно вказати email та password.")
        client = PocketOption(config.email, config.password)

    # Авторизація через Google-session (SSID)
    # Практично це токен/cookie-сесії після входу через Google в браузері.
    elif auth_method == "google":
        if not config.google_ssid:
            raise ValueError("Для Google-авторизації потрібно вказати SSID (токен сесії).")

        # Різні версії community-клієнтів мають різні сигнатури конструктора,
        # тому пробуємо кілька сумісних варіантів.
        try:
            client = PocketOption(config.google_ssid)
        except TypeError:
            try:
                client = PocketOption(ssid=config.google_ssid)
            except TypeError:
                client = PocketOption("", "", config.google_ssid)
    else:
        raise ValueError("Невідомий метод авторизації. Використайте 'password' або 'google'.")

    is_connected = client.connect()
    if not is_connected:
        raise ConnectionError("Не вдалося підключитися до Pocket Option.")

    return client


def fetch_ohlc_dataframe(client: Any, symbol: str, timeframe_sec: int, limit: int) -> pd.DataFrame:
    """Отримує OHLC-дані для пари та нормалізує до DataFrame."""
    end_time = int(time.time())
    start_time = end_time - timeframe_sec * limit

    candles = client.get_candles(symbol, timeframe_sec, start_time, end_time)
    if not candles:
        raise ValueError(f"Не отримано свічок для {symbol}.")

    df = pd.DataFrame(candles)
    df = df.rename(
        columns={
            "from": "timestamp",
            "time": "timestamp",
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
        }
    )

    required_cols = {"timestamp", "open", "high", "low", "close"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Некоректний формат свічок для {symbol}. Отримано: {list(df.columns)}")

    df = df[["timestamp", "open", "high", "low", "close"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna().sort_values("timestamp").reset_index(drop=True)


# =========================
# Торгова аналітика
# =========================
def calculate_profitability_percent(df: pd.DataFrame) -> float:
    if df.empty:
        return float("-inf")
    first_close = float(df.iloc[0]["close"])
    last_close = float(df.iloc[-1]["close"])
    if first_close == 0:
        return float("-inf")
    return ((last_close - first_close) / first_close) * 100


def analyze_pairs_profitability(
    client: Any,
    pairs: list[str],
    timeframe_sec: int,
    limit: int,
    log: Callable[[str], None],
) -> list[dict]:
    """Оцінює прибутковість по кожній валютній парі."""
    report: list[dict] = []
    log("Аналіз прибутковості пар...")

    for pair in pairs:
        try:
            df = fetch_ohlc_dataframe(client, pair, timeframe_sec, limit)
            profit_pct = calculate_profitability_percent(df)
            report.append({"symbol": pair, "profit_pct": profit_pct})
            log(f"- {pair}: {profit_pct:+.2f}%")
        except Exception as error:
            log(f"- {pair}: помилка ({error})")

    report.sort(key=lambda item: item["profit_pct"], reverse=True)
    return report


def select_pair(report: list[dict], auto_select_best_pair: bool) -> str:
    """Повертає найкращу пару або першу в списку (якщо auto вимкнено)."""
    if not report:
        raise RuntimeError("Немає пар для моніторингу після аналізу.")
    if auto_select_best_pair:
        return report[0]["symbol"]
    return report[0]["symbol"]


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["ema9"] = result["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    result["ema21"] = result["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()

    delta = result["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = losses.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()

    rs = avg_gain / avg_loss
    result["rsi"] = 100 - (100 / (1 + rs))
    return result


def detect_signal(df: pd.DataFrame) -> str:
    if len(df) < RSI_PERIOD + 2:
        return "NO SIGNAL"

    prev_candle = df.iloc[-2]
    curr_candle = df.iloc[-1]

    if pd.isna(curr_candle["rsi"]):
        return "NO SIGNAL"

    buy_signal = (
        prev_candle["ema9"] <= prev_candle["ema21"]
        and curr_candle["ema9"] > curr_candle["ema21"]
        and 45 <= curr_candle["rsi"] <= 70
        and curr_candle["close"] > curr_candle["ema21"]
    )

    sell_signal = (
        prev_candle["ema9"] >= prev_candle["ema21"]
        and curr_candle["ema9"] < curr_candle["ema21"]
        and 30 <= curr_candle["rsi"] <= 55
        and curr_candle["close"] < curr_candle["ema21"]
    )

    if buy_signal:
        return "BUY"
    if sell_signal:
        return "SELL"
    return "NO SIGNAL"


# =========================
# Логіка бота в окремому потоці
# =========================
def run_signal_bot(config: BotConfig, stop_event: threading.Event, log: Callable[[str], None]) -> None:
    client = create_pocketoption_client(config)
    log("Успішно підключено до Pocket Option.")

    report = analyze_pairs_profitability(
        client=client,
        pairs=config.pairs,
        timeframe_sec=config.timeframe_sec,
        limit=config.candles_limit,
        log=log,
    )
    for idx, row in enumerate(report, start=1):
        log(f"{idx}. {row['symbol']} ({row['profit_pct']:+.2f}%)")

    selected_pair = select_pair(report, config.auto_select_best_pair)
    log(f"Пара для моніторингу: {selected_pair}")

    last_signal_candle_timestamp = None
    last_signal_type = None

    while not stop_event.is_set():
        try:
            market_df = fetch_ohlc_dataframe(
                client=client,
                symbol=selected_pair,
                timeframe_sec=config.timeframe_sec,
                limit=config.candles_limit,
            )
            market_df = calculate_indicators(market_df)

            signal = detect_signal(market_df)
            current = market_df.iloc[-1]
            candle_timestamp = current["timestamp"]

            is_duplicate = (
                signal in ("BUY", "SELL")
                and candle_timestamp == last_signal_candle_timestamp
                and signal == last_signal_type
            )

            if signal in ("BUY", "SELL") and not is_duplicate:
                last_signal_candle_timestamp = candle_timestamp
                last_signal_type = signal

            now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            candle_str = candle_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            duplicate_label = " (дублікат пропущено)" if is_duplicate else ""

            log(
                f"[{now_local}] {selected_pair} {config.timeframe_sec}s | "
                f"Candle: {candle_str} | "
                f"Close: {float(current['close']):.6f} | "
                f"EMA9: {float(current['ema9']):.6f} | "
                f"EMA21: {float(current['ema21']):.6f} | "
                f"RSI: {float(current['rsi']):.2f} | "
                f"Signal: {signal}{duplicate_label}"
            )

            stop_event.wait(config.check_interval_sec)

        except Exception as error:
            log(f"[ПОМИЛКА API] {error}")
            stop_event.wait(config.api_retry_delay_sec)


# =========================
# GUI
# =========================
class SignalBotGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pocket Option Signal Bot")
        self.root.geometry("900x650")

        self.stop_event = threading.Event()
        self.bot_thread: threading.Thread | None = None

        self._build_form()

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        # Авторизація
        ttk.Label(frame, text="Метод авторизації:").grid(row=0, column=0, sticky="w")
        self.auth_method_var = tk.StringVar(value="password")
        auth_combo = ttk.Combobox(frame, textvariable=self.auth_method_var, values=["password", "google"], state="readonly")
        auth_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Email:").grid(row=1, column=0, sticky="w")
        self.email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_var).grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Password:").grid(row=2, column=0, sticky="w")
        self.password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.password_var, show="*").grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Google SSID:").grid(row=3, column=0, sticky="w")
        self.google_ssid_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.google_ssid_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        # Налаштування бота
        ttk.Label(frame, text="Валютні пари (через кому):").grid(row=4, column=0, sticky="w")
        self.pairs_var = tk.StringVar(value=", ".join(DEFAULT_FOREX_PAIRS))
        ttk.Entry(frame, textvariable=self.pairs_var).grid(row=4, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Таймфрейм (сек):").grid(row=5, column=0, sticky="w")
        self.timeframe_var = tk.StringVar(value=str(DEFAULT_TIMEFRAME_SEC))
        ttk.Entry(frame, textvariable=self.timeframe_var).grid(row=5, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Кількість свічок:").grid(row=6, column=0, sticky="w")
        self.limit_var = tk.StringVar(value=str(DEFAULT_CANDLES_LIMIT))
        ttk.Entry(frame, textvariable=self.limit_var).grid(row=6, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Інтервал перевірки (сек):").grid(row=7, column=0, sticky="w")
        self.check_var = tk.StringVar(value=str(DEFAULT_CHECK_INTERVAL_SEC))
        ttk.Entry(frame, textvariable=self.check_var).grid(row=7, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(frame, text="Пауза після помилки (сек):").grid(row=8, column=0, sticky="w")
        self.retry_var = tk.StringVar(value=str(DEFAULT_API_RETRY_DELAY_SEC))
        ttk.Entry(frame, textvariable=self.retry_var).grid(row=8, column=1, sticky="ew", padx=6, pady=4)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Автовибір найприбутковішої пари", variable=self.auto_var).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=4
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(btn_frame, text="Старт", command=self.start_bot).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Стоп", command=self.stop_bot).pack(side="left", padx=4)

        self.log_text = tk.Text(frame, height=22, wrap="word")
        self.log_text.grid(row=11, column=0, columnspan=2, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(11, weight=1)

    def log(self, text: str) -> None:
        def _append() -> None:
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
        self.root.after(0, _append)

    def _build_config(self) -> BotConfig:
        pairs = [pair.strip().upper() for pair in self.pairs_var.get().split(",") if pair.strip()]
        if not pairs:
            raise ValueError("Вкажіть хоча б одну валютну пару.")

        return BotConfig(
            auth_method=self.auth_method_var.get().strip().lower(),
            email=self.email_var.get().strip(),
            password=self.password_var.get(),
            google_ssid=self.google_ssid_var.get().strip(),
            pairs=pairs,
            auto_select_best_pair=self.auto_var.get(),
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

        def _runner() -> None:
            try:
                run_signal_bot(config, self.stop_event, self.log)
            except Exception as error:
                self.log(f"[КРИТИЧНА ПОМИЛКА] {error}")

        self.bot_thread = threading.Thread(target=_runner, daemon=True)
        self.bot_thread.start()
        self.log("Бот запущено.")

    def stop_bot(self) -> None:
        self.stop_event.set()
        self.log("Запит на зупинку відправлено.")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = SignalBotGUI()
    app.run()


if __name__ == "__main__":
    main()

# =========================
# Інструкція запуску:
# 1) Встановіть залежності:
#    pip install pandas pocketoptionapi
# 2) Запустіть:
#    python signal_bot_binance.py
# 3) У GUI оберіть метод авторизації:
#    - password: введіть Email + Password
#    - google: вставте Google SSID (сесію)
# =========================
