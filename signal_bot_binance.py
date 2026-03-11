"""
Signal Bot для Binance (лише аналіз, без відкриття угод).

Вимоги:
- Python 3
- ccxt
- pandas

Бот завантажує OHLCV-дані, рахує EMA(9), EMA(21), RSI(14)
та виводить сигнали BUY / SELL / NO SIGNAL у консоль.
"""

import time
from datetime import datetime

import ccxt
import pandas as pd


# =========================
# Константи налаштування
# =========================
SYMBOL = "BTC/USDT"          # Торгова пара
TIMEFRAME = "5m"            # Таймфрейм свічок
OHLCV_LIMIT = 150            # Кількість свічок для аналізу
CHECK_INTERVAL_SEC = 20      # Пауза між перевірками (секунди)
API_RETRY_DELAY_SEC = 10     # Пауза після API-помилки (секунди)

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14


def create_exchange() -> ccxt.binance:
    """Створює екземпляр біржі Binance через ccxt."""
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
        },
    })


def fetch_ohlcv_dataframe(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    limit: int,
) -> pd.DataFrame:
    """Отримує OHLCV з Binance і повертає DataFrame з базовими колонками."""
    raw_ohlcv = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(
        raw_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Додає в DataFrame індикатори EMA(9), EMA(21), RSI(14)."""
    result = df.copy()

    # EMA (експоненціальна ковзна середня)
    result["ema9"] = result["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    result["ema21"] = result["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()

    # RSI (Relative Strength Index) за класичною формулою через rolling mean
    delta = result["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = losses.rolling(window=RSI_PERIOD, min_periods=RSI_PERIOD).mean()

    rs = avg_gain / avg_loss
    result["rsi"] = 100 - (100 / (1 + rs))

    return result


def detect_signal(df: pd.DataFrame) -> str:
    """
    Визначає сигнал на основі двох останніх свічок.

    BUY:
    - на попередній свічці EMA9 <= EMA21
    - на поточній свічці EMA9 > EMA21
    - RSI від 45 до 70
    - close > EMA21

    SELL:
    - на попередній свічці EMA9 >= EMA21
    - на поточній свічці EMA9 < EMA21
    - RSI від 30 до 55
    - close < EMA21
    """
    if len(df) < RSI_PERIOD + 2:
        return "NO SIGNAL"

    previous_candle = df.iloc[-2]
    current_candle = df.iloc[-1]

    # Якщо RSI ще не розрахований через нестачу історії
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
    timeframe: str,
    candle_time: pd.Timestamp,
    close_price: float,
    ema9: float,
    ema21: float,
    rsi: float,
    duplicate: bool,
) -> None:
    """Акуратно друкує статус у консоль."""
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    candle_str = candle_time.strftime("%Y-%m-%d %H:%M:%S UTC")

    duplicate_label = " (дублікат пропущено)" if duplicate else ""

    print(
        f"[{now_local}] {symbol} {timeframe} | "
        f"Candle: {candle_str} | "
        f"Close: {close_price:.2f} | EMA9: {ema9:.2f} | EMA21: {ema21:.2f} | RSI: {rsi:.2f} | "
        f"Signal: {signal}{duplicate_label}",
        flush=True,
    )


def run_signal_bot() -> None:
    """Основний цикл роботи signal bot."""
    exchange = create_exchange()

    # Зберігаємо останню свічку, на якій уже був надрукований BUY/SELL,
    # щоб уникати дублювання сигналу в межах тієї самої свічки.
    last_signal_candle_timestamp = None
    last_signal_type = None

    print("Запуск Binance Signal Bot (без відкриття угод)...", flush=True)
    print(
        f"Пара: {SYMBOL} | Таймфрейм: {TIMEFRAME} | Інтервал перевірки: {CHECK_INTERVAL_SEC}с",
        flush=True,
    )

    while True:
        try:
            market_df = fetch_ohlcv_dataframe(
                exchange=exchange,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                limit=OHLCV_LIMIT,
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

            print_status(
                signal=signal,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                candle_time=candle_timestamp,
                close_price=float(current["close"]),
                ema9=float(current["ema9"]),
                ema21=float(current["ema21"]),
                rsi=float(current["rsi"]) if not pd.isna(current["rsi"]) else float("nan"),
                duplicate=is_duplicate,
            )

            time.sleep(CHECK_INTERVAL_SEC)

        except ccxt.NetworkError as error:
            print(f"[ПОМИЛКА МЕРЕЖІ] {error}", flush=True)
            time.sleep(API_RETRY_DELAY_SEC)
        except ccxt.ExchangeError as error:
            print(f"[ПОМИЛКА БІРЖІ] {error}", flush=True)
            time.sleep(API_RETRY_DELAY_SEC)
        except Exception as error:
            print(f"[НЕОЧІКУВАНА ПОМИЛКА] {error}", flush=True)
            time.sleep(API_RETRY_DELAY_SEC)


if __name__ == "__main__":
    run_signal_bot()

# =========================
# Інструкція запуску:
# 1) Встановіть залежності:
#    pip install ccxt pandas
# 2) Запустіть бота:
#    python signal_bot_binance.py
# =========================
