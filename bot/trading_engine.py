from dataclasses import dataclass

from .signals import TradeSignal


@dataclass
class TradeState:
    current_step: int = 0
    current_stake: float = 1.0


class TradingEngine:
    def __init__(self, base_stake: float, martingale: float, max_steps: int):
        self.base_stake = base_stake
        self.martingale = martingale
        self.max_steps = max_steps
        self.state = TradeState(current_step=0, current_stake=base_stake)

    def on_trade_result(self, is_win: bool) -> None:
        if is_win:
            self.state.current_step = 0
            self.state.current_stake = self.base_stake
            return

        if self.state.current_step < self.max_steps:
            self.state.current_step += 1
            self.state.current_stake *= self.martingale
        else:
            self.state.current_step = 0
            self.state.current_stake = self.base_stake

    def execute_signal(self, signal: TradeSignal, client, logger, duration_sec: int) -> None:
        logger.info(f"Signal received: {signal.symbol} {signal.direction}")
        logger.info("[TRADE] Executing trade")
        result = client.execute_trade(
            symbol=signal.symbol,
            direction=signal.direction,
            amount=self.state.current_stake,
            duration_sec=duration_sec,
        )

        if result.status == "SKIPPED":
            logger.warning("[TRADE] Client has no supported trade method; skipping execution")
            return

        is_win = result.profit > 0
        outcome = "WIN" if is_win else "LOSS"
        sign = "+" if result.profit >= 0 else ""
        logger.info(f"[RESULT] {outcome} {sign}{result.profit}$")
        self.on_trade_result(is_win)
