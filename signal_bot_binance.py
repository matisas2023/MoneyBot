"""
Signal Bot для POCKET OPTION (лише аналіз, без відкриття угод).

Що робить бот:
- Підключається до Pocket Option через неофіційний API-клієнт.
- Завантажує свічки (OHLC) для валютних пар.
- Аналізує прибутковість списку валютних пар і обирає пару для моніторингу.
- Розраховує EMA(9), EMA(21), RSI(14) без TA-Lib.
- Друкує BUY / SELL / NO SIGNAL у консоль.

Увага:
Pocket Option не має офіційного публічного Python SDK.
Скрипт нижче орієнтований на популярний community-клієнт `pocketoptionapi`.
"""

import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

try:
    # Приклад неофіційного клієнта Pocket Option
    from pocketoptionapi.stable_api import PocketOption
except ImportError:
    PocketOption = None


# =========================
# Константи налаштування
# =========================
TIMEFRAME_SEC = 300          # 300 сек = 5 хв
CANDLES_LIMIT = 150          # Кількість свічок для аналізу
CHECK_INTERVAL_SEC = 20      # Пауза між перевірками
API_RETRY_DELAY_SEC = 10     # Пауза після помилки API

# Валютні пари (Forex), які зазвичай доступні в Pocket Option
# За потреби змініть список під свій акаунт/регіон.
POCKETOPTION_FOREX_PAIRS = [
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

# Якщо True — бот автоматично бере найприбутковішу пару.
# Якщо False — дає вибір користувачу через консоль.
AUTO_SELECT_BEST_PAIR = True

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14

# ДАНІ ДЛЯ АВТОРИЗАЦІЇ (заповніть своїми)
PO_EMAIL = "your_email@example.com"
PO_PASSWORD = "your_password"


def create_pocketoption_client() -> Any:
    """Створює і підключає клієнт Pocket Option."""
    if PocketOption is None:
        raise ImportError(
            "Не знайдено модуль pocketoptionapi. Встановіть його перед запуском."
        )

    client = PocketOption(PO_EMAIL, PO_PASSWORD)
    is_connected = client.connect()
    if not is_connected:
        raise ConnectionError("Не вдалося підключитися до Pocket Option.")

    return client


def fetch_ohlc_dataframe(
    client: Any,
    symbol: str,
    timeframe_sec: int,
    limit: int,
) -> pd.DataFrame:
    """
    Отримує OHLC-дані з Pocket Option і повертає DataFrame.

    Очікуваний формат від клієнта: список свічок із полями на кшталт
    timestamp/open/high/low/close (назви можуть залежати від версії API).
    """
    end_time = int(time.time())
    start_time = end_time - (timeframe_sec * limit)

    candles = client.get_candles(symbol, timeframe_sec, start_time, end_time)

    if not candles:
        raise ValueError(f"Не отримано свічок для {symbol}.")

    df = pd.DataFrame(candles)

    # Уніфікація назв колонок (різні клієнти можуть повертати різні ключі)
    rename_map = {
        "from": "timestamp",
        "time": "timestamp",
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
    }
    df = df.rename(columns=rename_map)

    required_cols = {"timestamp", "open", "high", "low", "close"}
    if not required_cols.issubset(df.columns):
        raise ValueError(
            f"Некоректний формат свічок для {symbol}. Колонки: {list(df.columns)}"
        )

    df = df[["timestamp", "open", "high", "low", "close"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    return df


def calculate_profitability_percent(df: pd.DataFrame) -> float:
    """Рахує прибутковість у % за доступну історію."""
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
) -> list[dict]:
    """Аналізує прибутковість валютних пар PO і повертає рейтинг."""
    print("\nАналіз прибутковості валютних пар Pocket Option...", flush=True)
    report = []

    for pair in pairs:
        try:
            df = fetch_ohlc_dataframe(client, pair, timeframe_sec, limit)
            profit_pct = calculate_profitability_percent(df)
            report.append({"symbol": pair, "profit_pct": profit_pct})
            print(f"- {pair}: {profit_pct:+.2f}%", flush=True)
        except Exception as error:
            print(f"- {pair}: не вдалося отримати дані ({error})", flush=True)

    report.sort(key=lambda item: item["profit_pct"], reverse=True)
    return report


def choose_pair_from_report(report: list[dict]) -> str:
    """Обирає пару: автоматично найкращу або вручну з рейтингу."""
    if not report:
        raise RuntimeError("Немає доступних валютних пар для моніторингу.")

    print("\nРейтинг валютних пар за прибутковістю:", flush=True)
    for i, item in enumerate(report, start=1):
        print(f"{i}. {item['symbol']} ({item['profit_pct']:+.2f}%)", flush=True)

    if AUTO_SELECT_BEST_PAIR:
        selected = report[0]["symbol"]
        print(f"\nАвтовибір найприбутковішої пари: {selected}", flush=True)
        return selected

    while True:
        user_input = input("\nВведіть номер пари для моніторингу: ").strip()
        if not user_input.isdigit():
            print("Введіть коректне число.", flush=True)
            continue

        choice = int(user_input)
        if 1 <= choice <= len(report):
            selected = report[choice - 1]["symbol"]
            print(f"Обрано: {selected}", flush=True)
            return selected

        print("Номер поза межами списку.", flush=True)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Додає індикатори EMA(9), EMA(21), RSI(14)."""
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
    """Визначає BUY / SELL / NO SIGNAL за останніми двома свічками."""
    if len(df) < RSI_PERIOD + 2:
        return "NO SIGNAL"

    previous_candle = df.iloc[-2]
    current_candle = df.iloc[-1]

    if pd.isna(current_candle["rsi"]):
        return "NO SIGNAL"

    buy_signal = (
        previous_candle["ema9"] <= previous_candle["ema21"]
        and current_candle["ema9"] > current_candle["ema21"]
        and 45 <= current_candle["rsi"] <= 70
        and current_candle["close"] > current_candle["ema21"]
    )

    sell_signal = (
        previous_candle["ema9"] >= previous_candle["ema21"]
        and current_candle["ema9"] < current_candle["ema21"]
        and 30 <= current_candle["rsi"] <= 55
        and current_candle["close"] < current_candle["ema21"]
    )

    if buy_signal:
        return "BUY"
    if sell_signal:
        return "SELL"
    return "NO SIGNAL"


def print_status(
    signal: str,
    symbol: str,
    candle_time: pd.Timestamp,
    close_price: float,
    ema9: float,
    ema21: float,
    rsi: float,
    duplicate: bool,
) -> None:
    """Акуратний вивід статусу в консоль."""
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    candle_str = candle_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    duplicate_label = " (дублікат пропущено)" if duplicate else ""

    print(
        f"[{now_local}] {symbol} {TIMEFRAME_SEC}s | "
        f"Candle: {candle_str} | "
        f"Close: {close_price:.6f} | EMA9: {ema9:.6f} | EMA21: {ema21:.6f} | RSI: {rsi:.2f} | "
        f"Signal: {signal}{duplicate_label}",
        flush=True,
    )


def run_signal_bot() -> None:
    """Основний цикл signal bot для Pocket Option."""
    client = create_pocketoption_client()

    profitability_report = analyze_pairs_profitability(
        client=client,
        pairs=POCKETOPTION_FOREX_PAIRS,
        timeframe_sec=TIMEFRAME_SEC,
        limit=CANDLES_LIMIT,
    )
    selected_pair = choose_pair_from_report(profitability_report)

    last_signal_candle_timestamp = None
    last_signal_type = None

    print("\nЗапуск Pocket Option Signal Bot (без відкриття угод)...", flush=True)
    print(
        f"Пара: {selected_pair} | Таймфрейм: {TIMEFRAME_SEC}s | Інтервал перевірки: {CHECK_INTERVAL_SEC}с",
        flush=True,
    )

    while True:
        try:
            market_df = fetch_ohlc_dataframe(client, selected_pair, TIMEFRAME_SEC, CANDLES_LIMIT)
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

            print_status(
                signal=signal,
                symbol=selected_pair,
                candle_time=candle_timestamp,
                close_price=float(current["close"]),
                ema9=float(current["ema9"]),
                ema21=float(current["ema21"]),
                rsi=float(current["rsi"]) if not pd.isna(current["rsi"]) else float("nan"),
                duplicate=is_duplicate,
            )

            time.sleep(CHECK_INTERVAL_SEC)

        except Exception as error:
            # Універсальна обробка помилок API/мережі/формату даних
            print(f"[ПОМИЛКА API] {error}", flush=True)
            time.sleep(API_RETRY_DELAY_SEC)


def run() -> None:
    """Точка входу з базовим захистом від критичних помилок підключення."""
    try:
        run_signal_bot()
    except KeyboardInterrupt:
        print("\nЗупинено користувачем.", flush=True)
    except Exception as error:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{now_utc}] Критична помилка запуску: {error}", flush=True)


if __name__ == "__main__":
    run()

# =========================
# Інструкція запуску:
# 1) Встановіть залежності:
#    pip install pandas pocketoptionapi
# 2) Впишіть свої дані в PO_EMAIL і PO_PASSWORD.
# 3) За потреби змініть список POCKETOPTION_FOREX_PAIRS.
# 4) Запустіть:
#    python signal_bot_binance.py
# =========================
