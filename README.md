# tradingview-signal-router

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![Tests](https://img.shields.io/badge/Tests-114_passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

Receives webhook alerts from TradingView and automatically routes them to brokers for execution — with built-in risk management, position sizing, and paper trading.

## What does this do?

When you set up a TradingView alert with a webhook URL, this tool catches that alert, parses it into a trading signal, checks it against your risk rules, calculates the right position size, and sends the order to your broker.

```
TradingView Alert → Webhook POST → Parse Signal → Risk Check → Size Position → Execute Order
                                                                                    ↓
                                                                              PaperBroker (sim)
                                                                              CCXTBroker (live)
```

## How it works — module by module

### `parser.py` — Signal Parser

Converts raw webhook payloads into structured `Signal` objects. Supports three formats:

**JSON** (most common with TradingView):
```json
{"ticker": "BTCUSDT", "action": "buy", "price": 42000, "sl": 41000, "tp": 44000}
```

**Key-value text**:
```
ticker=BTCUSDT action=buy price=42000 sl=41000 tp=44000
```

**Python dict** (for programmatic use):
```python
from src.parser import SignalParser

parser = SignalParser()
signal = parser.parse('{"ticker": "ETHUSDT", "action": "sell", "price": 3200}')

print(signal.ticker)    # ETHUSDT
print(signal.side)      # Side.SELL
print(signal.price)     # 3200.0
```

The parser handles edge cases: missing fields get defaults, `"long"` maps to BUY, `"close_short"` maps to BUY, `"flatten"` maps to CLOSE. You can run it in strict mode to reject incomplete signals.

### `risk.py` — Risk Manager

Checks every signal against your risk rules before it reaches the broker. You configure limits, and anything that violates them gets rejected with a clear reason.

```python
from src.risk import RiskManager

risk = RiskManager(
    max_position_pct=0.02,      # Risk 2% of capital per trade
    max_daily_trades=20,        # No more than 20 trades per day
    max_daily_loss=500.0,       # Stop trading after $500 loss in a day
    max_open_positions=5,       # Max 5 simultaneous positions
    max_leverage=10,            # Cap leverage at 10x
    require_stop_loss=True,     # Every trade must have a stop-loss
    min_risk_reward=1.5,        # Minimum 1.5:1 reward-to-risk ratio
    allowed_tickers=["BTCUSDT", "ETHUSDT"],  # Whitelist (optional)
)

# Check a signal
result = risk.check(signal, capital=10000.0)
if result.passed:
    print(f"Trade approved, size: {result.quantity} units")
else:
    print(f"Rejected: {result.reason}")
```

Position sizing works automatically: if you set `max_position_pct=0.02` with $10,000 capital and BTC at $42,000 with a stop-loss at $41,000, it calculates the exact quantity so you risk exactly $200 (2% of capital).

### `brokers.py` — Broker Adapters

Two broker adapters share the same interface, so you can switch between paper and live trading without changing your code:

**PaperBroker** — simulates order execution locally:
```python
from src.brokers import PaperBroker

broker = PaperBroker(initial_balance=10000.0, slippage_pct=0.001)
broker.connect()

# Executes immediately at market price (with simulated slippage)
order = broker.submit_order(order)

# Check your simulated portfolio
print(broker.get_balance())     # 9580.50
print(broker.get_positions())   # [Position(BTCUSDT, qty=0.005)]
print(broker.get_stats())       # {trades: 1, win_rate: 0.0, ...}
```

**CCXTBroker** — connects to real crypto exchanges (Binance, Bybit, OKX, etc.):
```python
from src.brokers import CCXTBroker

broker = CCXTBroker(
    exchange="binance",
    api_key="your-key",
    secret="your-secret",
    sandbox=True,  # Use testnet first!
)
broker.connect()
```

### `router.py` — The Orchestrator

Ties everything together. You give it a broker and risk config, and it handles the full pipeline:

```python
from src.router import SignalRouter
from src.brokers import PaperBroker
from src.risk import RiskManager

router = SignalRouter(
    brokers={"paper": PaperBroker(initial_balance=10000)},
    risk_manager=RiskManager(max_position_pct=0.02),
    default_broker="paper",
    capital=10000.0,
)

# Route a raw webhook payload
result = router.route('{"ticker": "BTCUSDT", "action": "buy", "price": 42000, "sl": 41000}')
print(result)
# {"status": "filled", "order_id": "abc123", "fill_price": 42042.0, "quantity": 0.005}

# Check stats
stats = router.get_stats()
print(f"Accepted: {stats['signals_accepted']}, Rejected: {stats['signals_rejected']}")
```

**Paper mirror mode** — execute on live broker AND paper broker simultaneously to compare:
```python
router = SignalRouter(
    brokers={"binance": live_broker, "paper": paper_broker},
    default_broker="binance",
    paper_mirror=True,  # Also executes on paper broker
)
```

### `server.py` — Webhook Server

HTTP server that receives POST requests from TradingView. Includes HMAC-SHA256 signature verification so random requests can't trigger trades.

```python
from src.server import WebhookServer

server = WebhookServer(
    router=router,
    host="0.0.0.0",
    port=8080,
    webhook_secret="your-secret-key",  # For HMAC verification
)
server.start()
```

TradingView sends alerts to `http://your-server:8080/webhook`.

### `main.py` — CLI

```bash
# Start the webhook server
python -m src serve --port 8080 --capital 10000 --broker paper

# Parse a signal without executing (for testing)
python -m src parse '{"ticker": "BTCUSDT", "action": "buy", "price": 42000}'

# Run a quick paper trading simulation
python -m src paper-test
```

## Project Structure

```
tradingview-signal-router/
├── src/
│   ├── __init__.py         # Package metadata + public exports
│   ├── models.py           # Signal, Order, Position dataclasses + enums
│   ├── parser.py           # Multi-format signal parser (JSON/text/dict)
│   ├── risk.py             # Risk manager with position sizing
│   ├── brokers.py          # PaperBroker + CCXTBroker adapters
│   ├── router.py           # Main pipeline orchestrator
│   ├── server.py           # HTTP webhook server with HMAC auth
│   └── main.py             # CLI entry point (serve/parse/paper-test)
├── tests/
│   ├── test_models.py      # 22 tests — Signal, Order, Position, enums
│   ├── test_parser.py      # 31 tests — JSON, text, dict, edge cases
│   ├── test_risk.py        # 26 tests — limits, sizing, filters, R:R
│   ├── test_brokers.py     # 19 tests — orders, balance, positions, stats
│   └── test_router.py      # 16 tests — routing, hooks, stats, mirror
├── requirements.txt
├── LICENSE
└── README.md
```

## Installation

```bash
git clone https://github.com/DinhLucent/tradingview-signal-router.git
cd tradingview-signal-router
pip install -r requirements.txt
```

For live crypto trading, also install CCXT:
```bash
pip install ccxt
```

## Running Tests

```bash
# Run all 114 tests
python -m pytest tests/ -v

# Run a specific module
python -m pytest tests/test_risk.py -v

# Quick summary
python -m pytest tests/ -q
```

## Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_pct` | `0.02` | Max % of capital to risk per trade |
| `max_daily_trades` | `50` | Max trades per day before auto-stop |
| `max_daily_loss` | `None` | Daily loss limit in USD |
| `max_open_positions` | `10` | Max simultaneous open positions |
| `max_leverage` | `1` | Maximum allowed leverage |
| `require_stop_loss` | `False` | Require SL on every trade |
| `min_risk_reward` | `0.0` | Minimum reward:risk ratio (0 = disabled) |
| `allowed_tickers` | `[]` | Whitelist (empty = allow all) |
| `blocked_tickers` | `[]` | Blacklist |
| `max_order_value` | `None` | Max single order value in USD |

## License

MIT License — see [LICENSE](LICENSE)

---
Built by [DinhLucent](https://github.com/DinhLucent)
