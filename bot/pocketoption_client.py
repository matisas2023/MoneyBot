import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd


logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]
if hasattr(logging, "LoggerAdapter") and hasattr(logging.LoggerAdapter, "warning") and not hasattr(logging.LoggerAdapter, "warn"):
    logging.LoggerAdapter.warn = logging.LoggerAdapter.warning  # type: ignore[attr-defined]


try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
except ImportError:  # pragma: no cover
    PocketOption = None


@dataclass
class TradeResult:
    status: str
    profit: float = 0.0
    raw: Any = None


class PocketOptionClient:
    def __init__(self, ssid: str, demo: bool = True):
        if PocketOption is None:
            raise ImportError("BinaryOptionsToolsV2 is not installed. Run: pip install binaryoptionstoolsv2")
        self.raw = self._construct(ssid)
        self.demo = demo

    @staticmethod
    def _construct(ssid: str):
        try:
            return PocketOption(ssid=ssid)
        except TypeError:
            return PocketOption(ssid)

    def connect(self) -> bool:
        for method in ("connect", "login", "start"):
            fn = getattr(self.raw, method, None)
            if callable(fn):
                result = fn()
                return True if result is None else bool(result)
        return True

    def close(self) -> None:
        for method in ("close", "disconnect", "logout", "stop"):
            fn = getattr(self.raw, method, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:
                    continue

    def get_candles(self, symbol: str, timeframe_sec: int, limit: int) -> pd.DataFrame:
        end_time = int(time.time())
        start_time = end_time - timeframe_sec * limit

        candles = None
        for method in ("get_candles", "candles", "fetch_candles", "get_history"):
            fn = getattr(self.raw, method, None)
            if not callable(fn):
                continue
            try:
                candles = fn(symbol, timeframe_sec, start_time, end_time)
                break
            except TypeError:
                try:
                    candles = fn(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                    break
                except TypeError:
                    continue

        if not candles:
            raise ValueError(f"No candles for {symbol}")

        df = pd.DataFrame(candles).rename(
            columns={"from": "timestamp", "time": "timestamp", "t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close"}
        )
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"Unexpected candle format: {list(df.columns)}")

        out = df[["timestamp", "open", "high", "low", "close"]].copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"], unit="s", utc=True)
        for col in ("open", "high", "low", "close"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        return out.dropna().sort_values("timestamp").reset_index(drop=True)

    def execute_trade(self, symbol: str, direction: str, amount: float, duration_sec: int) -> TradeResult:
        for method in ("buy", "trade", "open_trade"):
            fn = getattr(self.raw, method, None)
            if not callable(fn):
                continue
            try:
                payload = fn(symbol, amount, direction, duration_sec)
            except TypeError:
                try:
                    payload = fn(symbol=symbol, amount=amount, action=direction, duration=duration_sec)
                except Exception:
                    continue
            status = str(getattr(payload, "status", "PLACED")) if payload is not None else "PLACED"
            profit = float(getattr(payload, "profit", 0.0) or 0.0)
            return TradeResult(status=status, profit=profit, raw=payload)
        return TradeResult(status="SKIPPED", profit=0.0, raw=None)
