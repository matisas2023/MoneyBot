from __future__ import annotations

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


@dataclass(slots=True)
class TradeResult:
    status: str
    profit: float = 0.0
    raw: Any = None


class ExternalServiceClient:
    def __init__(self, endpoint: str, api_key: str, api_secret: str, ssid: str, demo: bool = True):
        self.endpoint = endpoint
        self.api_key = api_key
        self.api_secret = api_secret
        self.ssid = ssid
        self.demo = demo
        self._client: Any | None = None

    def connect(self) -> bool:
        if PocketOption is None:
            raise ImportError("BinaryOptionsToolsV2 is not installed. Run: pip install binaryoptionstoolsv2")
        if not self.ssid:
            raise ValueError("client.ssid is required for PocketOption connection")

        self._client = self._construct_client(self.ssid)

        for method_name in ("connect", "login", "start"):
            method = getattr(self._client, method_name, None)
            if callable(method):
                result = method()
                return True if result is None else bool(result)
        return True

    def close(self) -> None:
        if self._client is None:
            return
        for method_name in ("close", "disconnect", "logout", "stop"):
            method = getattr(self._client, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except RuntimeError:
                    continue
                except ValueError:
                    continue

    @staticmethod
    def _construct_client(ssid: str):
        try:
            return PocketOption(ssid=ssid)
        except TypeError:
            return PocketOption(ssid)

    def fetch_candles(self, symbol: str, timeframe_sec: int, candles_limit: int) -> pd.DataFrame:
        if self._client is None:
            raise RuntimeError("Client is not connected")

        end_time = int(time.time())
        start_time = end_time - timeframe_sec * candles_limit
        payload: Any = None

        for method_name in ("get_candles", "candles", "fetch_candles", "get_history"):
            method = getattr(self._client, method_name, None)
            if not callable(method):
                continue
            try:
                payload = method(symbol, timeframe_sec, start_time, end_time)
                break
            except TypeError:
                try:
                    payload = method(symbol=symbol, timeframe=timeframe_sec, start=start_time, end=end_time)
                    break
                except TypeError:
                    continue

        if not payload:
            raise ValueError(f"No candles returned for {symbol}")

        frame = pd.DataFrame(payload).rename(
            columns={"from": "timestamp", "time": "timestamp", "t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close"}
        )
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(frame.columns):
            raise ValueError(f"Unexpected candles format for {symbol}: {list(frame.columns)}")

        normalized = frame[["timestamp", "open", "high", "low", "close"]].copy()
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], unit="s", utc=True)
        for column in ("open", "high", "low", "close"):
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        return normalized.dropna().sort_values("timestamp").reset_index(drop=True)

    def execute_trade(self, symbol: str, direction: str, amount: float, duration_sec: int) -> TradeResult:
        if self._client is None:
            raise RuntimeError("Client is not connected")

        for method_name in ("buy", "trade", "open_trade"):
            method = getattr(self._client, method_name, None)
            if not callable(method):
                continue
            try:
                response = method(symbol, amount, direction, duration_sec)
            except TypeError:
                try:
                    response = method(symbol=symbol, amount=amount, action=direction, duration=duration_sec)
                except TypeError:
                    continue
            status = str(getattr(response, "status", "PLACED")) if response is not None else "PLACED"
            profit = float(getattr(response, "profit", 0.0) or 0.0)
            return TradeResult(status=status, profit=profit, raw=response)

        return TradeResult(status="SKIPPED", profit=0.0, raw=None)
