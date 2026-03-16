# Headless CLI Bot

A fully headless (no GUI) Python bot architecture for terminal/VPS/Docker usage.

## Features
- CLI-only runtime (`python -m bot.main --config config.yaml`)
- YAML/JSON configuration loading and validation
- Console + file logging
- Modular architecture (`client`, `signals`, `engine`, `runner`)
- Graceful shutdown on `Ctrl+C`
- Reconnect attempt logic on runtime errors

## Project structure

```text
project/
  bot/
    __init__.py
    main.py
    config.py
    runner.py
    logger.py
    client.py
    signals.py
    engine.py
    utils.py
  config.yaml
  requirements.txt
  README.md
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m bot.main --config config.yaml
```

or

```bash
python signal_bot.py --config config.yaml
```

## Shutdown behavior
Press `Ctrl+C`:

- `Stopping bot...`
- `Closing PocketOption session...`
- `Shutdown complete.`

## Signals sources
- `signals.source: internal` — generate signals from internal EMA/RSI logic on market candles.
- `signals.source: demo` — stub signal generator for dry-run testing.
- `signals.source: file` — read textual signals from `signals.file_path`.

Example file signal lines:

```text
EURUSD CALL
GBPUSD PUT
USDJPY BUY
```

## Notes
- `client.py` is designed for integration with PocketOption (`BinaryOptionsToolsV2`).
- If real trade methods differ in your library build, update only `ExternalServiceClient.execute_trade()` adapters.
- No GUI dependencies are used.
