from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .signals import Signal


@dataclass(slots=True)
class EngineState:
    step: int = 0
    stake: float = 1.0


class TradingEngine:
    def __init__(self, base_stake: float, martingale: float, max_steps: int):
        self.base_stake = base_stake
        self.martingale = martingale
        self.max_steps = max_steps
        self.state = EngineState(step=0, stake=base_stake)

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["ema9"] = enriched["close"].ewm(span=9, adjust=False).mean()
        enriched["ema21"] = enriched["close"].ewm(span=21, adjust=False).mean()

        delta = enriched["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        enriched["rsi"] = 100 - (100 / (1 + rs))
        return enriched

    @staticmethod
    def detect_signal(df: pd.DataFrame) -> str:
        if len(df) < 3:
            return "NO SIGNAL"

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        if prev["ema9"] <= prev["ema21"] and curr["ema9"] > curr["ema21"] and curr["rsi"] < 70:
            return "CALL"
        if prev["ema9"] >= prev["ema21"] and curr["ema9"] < curr["ema21"] and curr["rsi"] > 30:
            return "PUT"
        return "NO SIGNAL"

    @staticmethod
    def profitability_percent(df: pd.DataFrame) -> float:
        if df.empty:
            return float("-inf")
        first_close = float(df.iloc[0]["close"])
        last_close = float(df.iloc[-1]["close"])
        if first_close == 0:
            return float("-inf")
        return (last_close - first_close) / abs(first_close) * 100.0

    def _on_trade_result(self, is_win: bool) -> None:
        if is_win:
            self.state = EngineState(step=0, stake=self.base_stake)
            return

        if self.state.step < self.max_steps:
            self.state.step += 1
            self.state.stake *= self.martingale
        else:
            self.state = EngineState(step=0, stake=self.base_stake)

    def process_signal(self, signal: Signal, client, logger, duration_sec: int) -> None:
        logger.info("Signal received: %s %s", signal.symbol, signal.direction)
        logger.info("[TRADE] Executing trade")

        result = client.execute_trade(
            symbol=signal.symbol,
            direction=signal.direction,
            amount=self.state.stake,
            duration_sec=duration_sec,
        )

        if result.status == "SKIPPED":
            logger.warning("[TRADE] No supported trade method in API client")
            return

        is_win = result.profit > 0
        outcome = "WIN" if is_win else "LOSS"
        sign = "+" if result.profit >= 0 else ""
        logger.info("[RESULT] %s %s%s$", outcome, sign, result.profit)
        self._on_trade_result(is_win)
