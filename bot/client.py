from __future__ import annotations

import logging
import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]
if hasattr(logging, "LoggerAdapter") and hasattr(logging.LoggerAdapter, "warning") and not hasattr(logging.LoggerAdapter, "warn"):
    logging.LoggerAdapter.warn = logging.LoggerAdapter.warning  # type: ignore[attr-defined]


try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
except ImportError:  # pragma: no cover
    PocketOption = None


def _patch_binaryoptions_warn_source() -> None:
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
    original = source

    helper = """

def _po_log_warn(logger_obj, message):
    if os.getenv("BOT_DEBUG_BINARYOPTIONS", "0") == "1":
        logger_cls = logger_obj.__class__
        print("[DEBUG] logger_type=", type(logger_obj), flush=True)
        print("[DEBUG] logger_class_module=", logger_cls.__module__, flush=True)
        print("[DEBUG] logger_class_name=", logger_cls.__name__, flush=True)
        print("[DEBUG] logger_mro=", logger_cls.__mro__, flush=True)
        print("[DEBUG] logger_public_methods=", [name for name in dir(logger_obj) if not name.startswith('_')], flush=True)
        print("[DEBUG] has_warn=", hasattr(logger_obj, "warn"), flush=True)
        print("[DEBUG] has_warning=", hasattr(logger_obj, "warning"), flush=True)
        print("[DEBUG] has_info=", hasattr(logger_obj, "info"), flush=True)
        print("[DEBUG] has_debug=", hasattr(logger_obj, "debug"), flush=True)
        print("[DEBUG] has_error=", hasattr(logger_obj, "error"), flush=True)
        print("[DEBUG] has_log=", hasattr(logger_obj, "log"), flush=True)

    for method_name in ("warning", "warn", "info", "debug", "error"):
        method = getattr(logger_obj, method_name, None)
        if callable(method):
            method(message)
            return

    method = getattr(logger_obj, "log", None)
    if callable(method):
        method(message)

"""

    if "def _po_log_warn(logger_obj, message):" not in source:
        if "import os" not in source:
            source = "import os\n" + source
        source = source + helper

    source = source.replace(
        "self.logger.warn(f\"SSID does not start with '42[': {ssid[:20]}...\")",
        "_po_log_warn(self.logger, f\"SSID does not start with '42[': {ssid[:20]}...\")",
    )
    source = source.replace(
        "self.logger.warning(f\"SSID does not start with '42[': {ssid[:20]}...\")",
        "_po_log_warn(self.logger, f\"SSID does not start with '42[': {ssid[:20]}...\")",
    )

    if source != original:
        source_path.write_text(source, encoding="utf-8")


def _debug_binaryoptions_runtime() -> None:
    if os.getenv("BOT_DEBUG_BINARYOPTIONS", "0") != "1":
        return

    try:
        from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
        from BinaryOptionsToolsV2.pocketoption import synchronous as po_sync  # type: ignore
    except ImportError:
        return

    print("[DEBUG] asynchronous.__file__=", getattr(po_async, "__file__", None), flush=True)
    print("[DEBUG] synchronous.__file__=", getattr(po_sync, "__file__", None), flush=True)

    async_cls = getattr(po_async, "PocketOptionAsync", None)
    if async_cls is not None:
        print("[DEBUG] PocketOptionAsync.__module__=", getattr(async_cls, "__module__", None), flush=True)
        init_fn = getattr(async_cls, "__init__", None)
        code = getattr(init_fn, "__code__", None)
        print("[DEBUG] PocketOptionAsync.__init__.co_filename=", getattr(code, "co_filename", None), flush=True)

    logger_obj = getattr(po_async, "logger", None)
    if logger_obj is not None:
        logger_cls = logger_obj.__class__
        print("[DEBUG] logger_type=", type(logger_obj), flush=True)
        print("[DEBUG] logger_class_module=", logger_cls.__module__, flush=True)
        print("[DEBUG] logger_class_name=", logger_cls.__name__, flush=True)
        print("[DEBUG] logger_mro=", logger_cls.__mro__, flush=True)
        print("[DEBUG] logger_public_methods=", [name for name in dir(logger_obj) if not name.startswith("_")], flush=True)
        print("[DEBUG] has_warn=", hasattr(logger_obj, "warn"), flush=True)
        print("[DEBUG] has_warning=", hasattr(logger_obj, "warning"), flush=True)
        print("[DEBUG] has_info=", hasattr(logger_obj, "info"), flush=True)
        print("[DEBUG] has_debug=", hasattr(logger_obj, "debug"), flush=True)
        print("[DEBUG] has_error=", hasattr(logger_obj, "error"), flush=True)
        print("[DEBUG] has_log=", hasattr(logger_obj, "log"), flush=True)


def _apply_warn_compat_for_binaryoptions() -> None:
    _patch_binaryoptions_warn_source()
    _debug_binaryoptions_runtime()

    if hasattr(logging.Logger, "warning") and not hasattr(logging.Logger, "warn"):
        logging.Logger.warn = logging.Logger.warning  # type: ignore[attr-defined]
    if (
        hasattr(logging, "LoggerAdapter")
        and hasattr(logging.LoggerAdapter, "warning")
        and not hasattr(logging.LoggerAdapter, "warn")
    ):
        logging.LoggerAdapter.warn = logging.LoggerAdapter.warning  # type: ignore[attr-defined]

    try:
        from BinaryOptionsToolsV2.pocketoption import asynchronous as po_async  # type: ignore
    except ImportError:
        return

    module_logger = getattr(po_async, "logger", None)
    if module_logger is not None and hasattr(module_logger, "warning") and not hasattr(module_logger, "warn"):
        setattr(module_logger, "warn", module_logger.warning)

    logger_cls = module_logger.__class__ if module_logger is not None else None
    if isinstance(logger_cls, type) and hasattr(logger_cls, "warning") and not hasattr(logger_cls, "warn"):
        setattr(logger_cls, "warn", logger_cls.warning)

    for candidate in vars(po_async).values():
        if isinstance(candidate, type) and hasattr(candidate, "warning") and not hasattr(candidate, "warn"):
            setattr(candidate, "warn", candidate.warning)


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
        _apply_warn_compat_for_binaryoptions()
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
        _apply_warn_compat_for_binaryoptions()
        try:
            return PocketOption(ssid=ssid)
        except TypeError:
            return PocketOption(ssid)
        except AttributeError:
            if os.getenv("BOT_DEBUG_BINARYOPTIONS", "0") == "1":
                print(traceback.format_exc(), flush=True)
            raise

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
