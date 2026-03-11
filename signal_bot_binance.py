"""
Signal Bot для Binance (лише аналіз, без відкриття угод).

Вимоги:
- Python 3
- ccxt
- pandas

Бот бере за основу список активів Pocket Option, мапить їх у символи Binance,
оцінює прибутковість кандидатів, обирає одну пару для моніторингу,
рахує EMA(9), EMA(21), RSI(14) та виводить BUY / SELL / NO SIGNAL.
"""

import time
from datetime import datetime

import ccxt
import pandas as pd


# =========================
# Константи налаштування
# =========================
TIMEFRAME = "5m"             # Таймфрейм свічок
OHLCV_LIMIT = 150             # Кількість свічок для аналізу
CHECK_INTERVAL_SEC = 20       # Пауза між перевірками (секунди)
API_RETRY_DELAY_SEC = 10      # Пауза після API-помилки (секунди)

# Список активів Pocket Option (база для вибору пар)
POCKETOPTION_BASE_ASSETS = [
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "LTC",
    "TRX",
    "DOT",
]

# Котирувальна валюта для Binance
QUOTE_ASSET = "USDT"

# Якщо True — автоматично беремо найприбутковішу пару.
# Якщо False — користувач обирає пару з рейтингу вручну.
AUTO_SELECT_BEST_PAIR = True

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


def build_symbol_from_base(base_asset: str, quote_asset: str) -> str:
    """Формує символ Binance, напр. BTC + USDT -> BTC/USDT."""
    return f"{base_asset.upper()}/{quote_asset.upper()}"


def resolve_pocketoption_symbols(exchange: ccxt.binance) -> list[str]:
    """
    Формує список Binance-пар на основі активів Pocket Option
    і залишає лише ті, що реально доступні на Binance Spot.
    """
    markets = exchange.load_markets()
    candidates = [build_symbol_from_base(base, QUOTE_ASSET) for base in POCKETOPTION_BASE_ASSETS]

    available_symbols = []
    for symbol in candidates:
        market = markets.get(symbol)
        if market and market.get("spot"):
            available_symbols.append(symbol)

    if not available_symbols:
        raise RuntimeError("Не знайдено доступних Binance Spot пар зі списку Pocket Option.")

    return available_symbols


def fetch_ohlcv_dataframe(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    limit: int,
) -> pd.DataFrame:
    """Отримує OHLCV з Binance і повертає DataFrame з базовими колонками."""
    raw_ohlcv = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def calculate_profitability_percent(df: pd.DataFrame) -> float:
    """Рахує прибутковість у %: (останній close - перший close) / перший close."""
    if df.empty:
        return float("-inf")

    first_close = float(df.iloc[0]["close"])
    last_close = float(df.iloc[-1]["close"])

    if first_close == 0:
        return float("-inf")

    return ((last_close - first_close) / first_close) * 100


def analyze_symbols_profitability(
    exchange: ccxt.binance,
    symbols: list[str],
    timeframe: str,
    limit: int,
) -> list[dict]:
    """Аналізує прибутковість кожної пари та повертає відсортований рейтинг."""
    report = []
    print("\nАналіз прибутковості пар (Pocket Option -> Binance):", flush=True)

    for symbol in symbols:
        try:
            ohlcv_df = fetch_ohlcv_dataframe(exchange, symbol, timeframe, limit)
            profit_pct = calculate_profitability_percent(ohlcv_df)
            report.append({"symbol": symbol, "profit_pct": profit_pct})
            print(f"- {symbol}: {profit_pct:+.2f}%", flush=True)
        except Exception as error:
            print(f"- {symbol}: не вдалося отримати дані ({error})", flush=True)

    report.sort(key=lambda item: item["profit_pct"], reverse=True)
    return report


def choose_symbol_from_profitability(report: list[dict]) -> str:
    """Обирає пару: автоматично найкращу або вручну з рейтингу."""
    if not report:
        raise RuntimeError("Немає доступних пар для аналізу прибутковості.")

    print("\nРейтинг пар за прибутковістю:", flush=True)
    for index, item in enumerate(report, start=1):
        print(f"{index}. {item['symbol']} ({item['profit_pct']:+.2f}%)", flush=True)

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
    """Додає в DataFrame індикатори EMA(9), EMA(21), RSI(14)."""
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
    """Визначає BUY / SELL / NO SIGNAL на основі двох останніх свічок."""
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
        f"Close: {close_price:.6f} | EMA9: {ema9:.6f} | EMA21: {ema21:.6f} | RSI: {rsi:.2f} | "
        f"Signal: {signal}{duplicate_label}",
        flush=True,
    )


def run_signal_bot() -> None:
    """Основний цикл роботи signal bot."""
    exchange = create_exchange()

    candidate_symbols = resolve_pocketoption_symbols(exchange)
    profitability_report = analyze_symbols_profitability(
        exchange=exchange,
        symbols=candidate_symbols,
        timeframe=TIMEFRAME,
        limit=OHLCV_LIMIT,
    )
    selected_symbol = choose_symbol_from_profitability(profitability_report)

    last_signal_candle_timestamp = None
    last_signal_type = None

    print("\nЗапуск Binance Signal Bot (без відкриття угод)...", flush=True)
    print(
        f"Пара: {selected_symbol} | Таймфрейм: {TIMEFRAME} | Інтервал перевірки: {CHECK_INTERVAL_SEC}с",
        flush=True,
    )

    while True:
        try:
            market_df = fetch_ohlcv_dataframe(exchange, selected_symbol, TIMEFRAME, OHLCV_LIMIT)
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
                symbol=selected_symbol,
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
# 2) За потреби змініть POCKETOPTION_BASE_ASSETS / QUOTE_ASSET / TIMEFRAME.
# 3) Запустіть бота:
#    python signal_bot_binance.py
# =========================
