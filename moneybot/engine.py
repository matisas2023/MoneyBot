import time
import traceback
from typing import Callable

from .config import BotConfig
from .pocketoption_client import create_pocketoption_client, fetch_ohlc_dataframe
from .strategy import calculate_indicators, calculate_profitability_percent, detect_signal


def analyze_pairs_profitability(config: BotConfig, client, log: Callable[[str], None]) -> str:
    best_pair = config.pairs[0]
    best_profit = float("-inf")
    for symbol in config.pairs:
        try:
            df = fetch_ohlc_dataframe(client, symbol, config.timeframe_sec, config.candles_limit)
            profit = calculate_profitability_percent(df)
            if profit > best_profit:
                best_profit = profit
                best_pair = symbol
        except Exception as error:
            log(f"[WARN] Не вдалося оцінити {symbol}: {error}")
    return best_pair


def run_signal_bot(config: BotConfig, stop_event, log: Callable[[str], None]) -> None:
    client = create_pocketoption_client(config, log)
    log("Бот запущено.")
    last_signal = None

    while not stop_event.is_set():
        try:
            symbol = analyze_pairs_profitability(config, client, log)
            df = fetch_ohlc_dataframe(client, symbol, config.timeframe_sec, config.candles_limit)
            enriched = calculate_indicators(df)
            signal = detect_signal(enriched)
            if signal != last_signal:
                log(f"[{symbol}] {signal}")
                last_signal = signal
        except Exception as error:
            log(f"[КРИТИЧНА ПОМИЛКА] {error}")
            for line in traceback.format_exc().rstrip().splitlines():
                log(f"[TRACE] {line}")
            time.sleep(config.api_retry_delay_sec)
            continue

        time.sleep(config.check_interval_sec)
