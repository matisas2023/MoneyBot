import pandas as pd

from .config import EMA_FAST_PERIOD, EMA_SLOW_PERIOD, RSI_PERIOD


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["ema9"] = data["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    data["ema21"] = data["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()

    delta = data["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, pd.NA)
    data["rsi"] = 100 - (100 / (1 + rs))
    return data


def detect_signal(df: pd.DataFrame) -> str:
    if len(df) < 3:
        return "NO SIGNAL"
    prev = df.iloc[-2]
    cur = df.iloc[-1]

    if prev["ema9"] <= prev["ema21"] and cur["ema9"] > cur["ema21"] and cur["rsi"] < 70:
        return "BUY"
    if prev["ema9"] >= prev["ema21"] and cur["ema9"] < cur["ema21"] and cur["rsi"] > 30:
        return "SELL"
    return "NO SIGNAL"


def calculate_profitability_percent(df: pd.DataFrame) -> float:
    if df.empty:
        return float("-inf")
    first_close = float(df.iloc[0]["close"])
    last_close = float(df.iloc[-1]["close"])
    if first_close == 0:
        return float("-inf")
    return (last_close - first_close) / abs(first_close) * 100.0
