import traceback
from threading import Event

from .config import AppConfig
from .pocketoption_client import PocketOptionClient
from .signals import FileSignalSource, TradeSignal
from .trading_engine import TradingEngine
from .utils import sleep_with_stop

import pandas as pd


class BotRunner:
    def __init__(self, config: AppConfig, logger):
        self.config = config
        self.logger = logger
        self.stop_event = Event()
        self.client = PocketOptionClient(config.pocketoption.ssid, demo=config.pocketoption.demo)
        self.trading_engine = TradingEngine(
            base_stake=config.trading.stake,
            martingale=config.trading.martingale,
            max_steps=config.trading.max_steps,
        )
        self.signal_source = FileSignalSource(config.signals.file_path) if config.signals.source == "file" and config.signals.file_path else None
        self.last_signal_key: tuple[str, str, str] | None = None

    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        data["ema9"] = data["close"].ewm(span=9, adjust=False).mean()
        data["ema21"] = data["close"].ewm(span=21, adjust=False).mean()

        delta = data["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        data["rsi"] = 100 - (100 / (1 + rs))
        return data

    @staticmethod
    def _detect_signal(df: pd.DataFrame) -> str:
        if len(df) < 3:
            return "NO SIGNAL"
        prev = df.iloc[-2]
        cur = df.iloc[-1]
        if prev["ema9"] <= prev["ema21"] and cur["ema9"] > cur["ema21"] and cur["rsi"] < 70:
            return "CALL"
        if prev["ema9"] >= prev["ema21"] and cur["ema9"] < cur["ema21"] and cur["rsi"] > 30:
            return "PUT"
        return "NO SIGNAL"

    @staticmethod
    def _profitability(df: pd.DataFrame) -> float:
        if df.empty:
            return float("-inf")
        first_close = float(df.iloc[0]["close"])
        last_close = float(df.iloc[-1]["close"])
        if first_close == 0:
            return float("-inf")
        return (last_close - first_close) / abs(first_close) * 100.0

    def _select_best_pair(self) -> str:
        best_pair = self.config.trading.pairs[0]
        best_profit = float("-inf")
        for symbol in self.config.trading.pairs:
            try:
                df = self.client.get_candles(symbol, self.config.trading.timeframe_sec, self.config.trading.candles_limit)
                profit = self._profitability(df)
                if profit > best_profit:
                    best_profit = profit
                    best_pair = symbol
            except Exception as error:
                self.logger.warning(f"Failed to evaluate {symbol}: {error}")
        return best_pair

    def _internal_signal(self) -> TradeSignal | None:
        symbol = self._select_best_pair()
        df = self.client.get_candles(symbol, self.config.trading.timeframe_sec, self.config.trading.candles_limit)
        enriched = self._calculate_indicators(df)
        signal = self._detect_signal(enriched)
        if signal == "NO SIGNAL":
            return None

        candle_ts = str(enriched.iloc[-1]["timestamp"])
        signal_key = (symbol, signal, candle_ts)
        if signal_key == self.last_signal_key:
            return None

        self.last_signal_key = signal_key
        return TradeSignal(symbol=symbol, direction=signal, source="internal")

    def _collect_signals(self) -> list[TradeSignal]:
        if self.config.signals.source == "internal":
            sig = self._internal_signal()
            return [sig] if sig else []

        if self.signal_source is not None:
            return self.signal_source.poll()

        self.logger.warning(f"Signal source '{self.config.signals.source}' is not configured. Falling back to internal mode.")
        sig = self._internal_signal()
        return [sig] if sig else []

    def run(self) -> None:
        self.logger.info("Bot started")
        if not self.client.connect():
            raise ConnectionError("Could not connect to PocketOption")
        self.logger.info("Connected to PocketOption")

        while not self.stop_event.is_set():
            try:
                signals = self._collect_signals()
                for signal in signals:
                    self.trading_engine.execute_signal(
                        signal=signal,
                        client=self.client,
                        logger=self.logger,
                        duration_sec=self.config.trading.timeframe_sec,
                    )
            except Exception as error:
                self.logger.error(f"Runtime error: {error}")
                self.logger.debug(traceback.format_exc())
                sleep_with_stop(self.stop_event, self.config.trading.api_retry_delay_sec)
                continue

            sleep_with_stop(self.stop_event, self.config.trading.check_interval_sec)

    def stop(self) -> None:
        self.stop_event.set()
        self.logger.info("Closing PocketOption session...")
        self.client.close()
