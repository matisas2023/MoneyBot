from __future__ import annotations

import logging
from threading import Event

from .client import ExternalServiceClient
from .config import Settings
from .engine import TradingEngine
from .signals import DemoSignalSource, FileSignalSource, Signal, SignalSource
from .utils import sleep_interruptible


class BotRunner:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.stop_event = Event()

        self.client = ExternalServiceClient(
            endpoint=settings.client.endpoint,
            api_key=settings.client.api_key,
            api_secret=settings.client.api_secret,
            ssid=settings.client.ssid,
            demo=settings.client.demo,
        )
        self.engine = TradingEngine(
            base_stake=settings.engine.stake,
            martingale=settings.engine.martingale,
            max_steps=settings.engine.max_steps,
        )
        self.signal_source = self._build_signal_source()
        self.last_internal_signal_key: tuple[str, str, str] | None = None

    def _build_signal_source(self) -> SignalSource:
        source = self.settings.signals.source
        if source == "demo":
            return DemoSignalSource(self.settings.engine.pairs or [])
        if source == "file" and self.settings.signals.file_path:
            return FileSignalSource(self.settings.signals.file_path)

        self.logger.warning("Unknown signal source '%s', fallback to demo", source)
        return DemoSignalSource(self.settings.engine.pairs or [])

    def start(self) -> None:
        self.logger.info("Bot started")
        connected = self.client.connect()
        if not connected:
            raise ConnectionError("Could not connect to PocketOption")
        self.logger.info("Connected to PocketOption")

        while not self.stop_event.is_set():
            if not self.settings.engine.enabled:
                sleep_interruptible(self.stop_event, self.settings.engine.poll_interval)
                continue

            try:
                signals = self._collect_signals()
                for signal in signals:
                    self.engine.process_signal(
                        signal=signal,
                        client=self.client,
                        logger=self.logger,
                        duration_sec=self.settings.engine.timeframe_sec,
                    )
            except (RuntimeError, ValueError, ConnectionError) as error:
                self.logger.error("Runtime error: %s", error)
                self._attempt_reconnect()

            sleep_interruptible(self.stop_event, self.settings.engine.poll_interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.logger.info("Closing PocketOption session...")
        self.client.close()

    def _collect_signals(self) -> list[Signal]:
        if self.settings.signals.source != "internal":
            return self.signal_source.poll()

        signal = self._generate_internal_signal()
        return [signal] if signal else []

    def _generate_internal_signal(self) -> Signal | None:
        symbol = self._select_best_pair()
        candles = self.client.fetch_candles(
            symbol=symbol,
            timeframe_sec=self.settings.engine.timeframe_sec,
            candles_limit=self.settings.engine.candles_limit,
        )
        enriched = self.engine.calculate_indicators(candles)
        direction = self.engine.detect_signal(enriched)
        if direction == "NO SIGNAL":
            return None

        candle_time = str(enriched.iloc[-1]["timestamp"])
        signal_key = (symbol, direction, candle_time)
        if signal_key == self.last_internal_signal_key:
            return None
        self.last_internal_signal_key = signal_key

        return Signal(symbol=symbol, direction=direction, source="internal")

    def _select_best_pair(self) -> str:
        pairs = self.settings.engine.pairs or []
        best_pair = pairs[0]
        best_profitability = float("-inf")

        for symbol in pairs:
            try:
                candles = self.client.fetch_candles(
                    symbol=symbol,
                    timeframe_sec=self.settings.engine.timeframe_sec,
                    candles_limit=self.settings.engine.candles_limit,
                )
                profitability = self.engine.profitability_percent(candles)
                if profitability > best_profitability:
                    best_profitability = profitability
                    best_pair = symbol
            except (RuntimeError, ValueError) as error:
                self.logger.warning("Failed to evaluate pair %s: %s", symbol, error)

        return best_pair

    def _attempt_reconnect(self) -> None:
        self.logger.info("Attempting reconnect...")
        self.client.close()
        connected = self.client.connect()
        if connected:
            self.logger.info("Reconnect successful")
        else:
            raise ConnectionError("Reconnect failed")
