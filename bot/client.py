from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
except ImportError:  # pragma: no cover
    PocketOption = None


def _remove_ssid_diagnostic_logging() -> None:
    try:
        from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
    except ImportError:
        return

    module_file = getattr(po_async, "__file__", "")
    if not module_file:
        return

    source_path = Path(module_file)
    if not source_path.exists():
        return

    source = source_path.read_text(encoding="utf-8")
    patched = re.sub(
        r'if ssid is not None and not ssid\.startswith\("42\["\):\n(?:[ \t]+(?:self\.logger\.(?:warn|warning)\(.*\)|_po_log_warn\(.*\))\n)+',
        'if ssid is not None and not ssid.startswith("42["):\n            pass\n',
        source,
    )

    if patched != source:
        source_path.write_text(patched, encoding="utf-8")


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
        _remove_ssid_diagnostic_logging()

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
        _remove_ssid_diagnostic_logging()
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
