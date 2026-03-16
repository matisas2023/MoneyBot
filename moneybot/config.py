from dataclasses import dataclass

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
    timeframe_sec: int = DEFAULT_TIMEFRAME_SEC
    candles_limit: int = DEFAULT_CANDLES_LIMIT
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC
    api_retry_delay_sec: int = DEFAULT_API_RETRY_DELAY_SEC
