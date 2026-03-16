import traceback
from typing import Any, Callable

import pandas as pd

from .config import BotConfig
from .logging_compat import (
    logger,
    patch_loaded_logger_classes_warn_alias,
    patch_logger_warn_compat,
    patch_third_party_warn_compat,
    debug_logger_shape,
)

try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
    from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
except ImportError:
    PocketOption = None
    po_async = None


def ensure_binaryoptions_warn_compat() -> None:
    if po_async is None:
        return

    patch_loaded_logger_classes_warn_alias()
    patch_third_party_warn_compat()

    # If library uses std logging internally, enforce class-level aliases.
    async_logging = getattr(po_async, "logging", None)
    if async_logging is not None:
        for name in ("Logger", "LoggerAdapter"):
            cls = getattr(async_logging, name, None)
            if isinstance(cls, type) and hasattr(cls, "warning") and not hasattr(cls, "warn"):
                setattr(cls, "warn", cls.warning)


def construct_pocketoption(*args, **kwargs):
    if PocketOption is None:
        raise ImportError("Library BinaryOptionsToolsV2 not installed. Run: pip install binaryoptionstoolsv2")
    ensure_binaryoptions_warn_compat()
    try:
        return PocketOption(*args, **kwargs)
    except AttributeError as error:
        if "warn" in str(error).lower():
            ensure_binaryoptions_warn_compat()
            return PocketOption(*args, **kwargs)
        raise


class PocketOptionDataClient:
    def __init__(self, raw_client: Any):
        self.raw_client = raw_client

    def connect(self) -> bool:
        for name in ("connect", "login", "start"):
            fn = getattr(self.raw_client, name, None)
            if callable(fn):
                result = fn()
                return True if result is None else bool(result)
        return True

    def get_candles(self, symbol: str, timeframe_sec: int, start_time: int, end_time: int):
        for name in ("get_candles", "candles", "fetch_candles", "get_history"):
            fn = getattr(self.raw_client, name, None)
            if not callable(fn):
                continue
            try:
                return fn(symbol, timeframe_sec, start_time, end_time)
            except TypeError:
                try:
                    return fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                except TypeError:
                    continue
        raise AttributeError("У client не знайдено сумісний метод отримання свічок.")


def create_pocketoption_client(config: BotConfig, log: Callable[[str], None]) -> PocketOptionDataClient:
    if not config.google_ssid:
        raise ValueError("Для BinaryOptionsToolsV2 потрібен SSID (режим google).")

    try:
        try:
            raw_client = construct_pocketoption(ssid=config.google_ssid)
        except TypeError:
            raw_client = construct_pocketoption(config.google_ssid)

        patch_logger_warn_compat(raw_client)
        client = PocketOptionDataClient(raw_client)
        if not client.connect():
            raise ConnectionError("Не вдалося підключитися до Pocket Option.")
        return client
    except Exception:
        raw_logger = getattr(getattr(po_async, "logger", None), "__class__", None) if po_async is not None else None
        if raw_logger is not None:
            log(debug_logger_shape(getattr(po_async, "logger", None)))
        log(traceback.format_exc())
        raise


def fetch_ohlc_dataframe(client: PocketOptionDataClient, symbol: str, timeframe_sec: int, limit: int) -> pd.DataFrame:
    import time

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
