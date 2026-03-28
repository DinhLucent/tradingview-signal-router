"""
tradingview-signal-router — CLI entry point.

Usage:
    python -m src serve --port 8080
    python -m src paper-test
    python -m src parse '{"ticker":"BTCUSDT","action":"buy","price":42000}'
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from .brokers import PaperBroker
from .parser import SignalParser
from .risk import RiskConfig
from .router import RouterConfig, SignalRouter
from .server import WebhookServer


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tradingview-signal-router",
        description="TradingView webhook signal router for multi-broker execution",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_cmd = sub.add_parser("serve", help="Start webhook server")
    serve_cmd.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_cmd.add_argument("--port", type=int, default=8080, help="Bind port")
    serve_cmd.add_argument("--secret", default="", help="Webhook secret")
    serve_cmd.add_argument(
        "--capital", type=float, default=10000, help="Paper trading capital"
    )

    # parse
    parse_cmd = sub.add_parser("parse", help="Parse a signal payload")
    parse_cmd.add_argument("payload", help="JSON string or plain text signal")

    # paper-test
    paper_cmd = sub.add_parser("paper-test", help="Run paper trading simulation")
    paper_cmd.add_argument(
        "--capital", type=float, default=10000, help="Starting capital"
    )

    # stats
    sub.add_parser("stats", help="Show current statistics")

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    if args.command == "serve":
        return _cmd_serve(args)
    elif args.command == "parse":
        return _cmd_parse(args)
    elif args.command == "paper-test":
        return _cmd_paper_test(args)
    else:
        parse_args(["--help"])
        return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the webhook server with paper broker."""
    router_config = RouterConfig(
        default_broker="paper",
        webhook_secret=args.secret,
    )
    router = SignalRouter(config=router_config, capital=args.capital)

    paper = PaperBroker(initial_balance=args.capital)
    paper.connect()
    router.register_broker(paper)

    server = WebhookServer(
        router=router,
        host=args.host,
        port=args.port,
        webhook_secret=args.secret,
    )

    print(f"🚀 Signal Router listening on {args.host}:{args.port}")
    print(f"💰 Paper trading with ${args.capital:,.2f}")
    print(f"📡 POST /webhook to send signals")
    server.start()
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    """Parse and display a signal."""
    parser = SignalParser()
    try:
        signal = parser.parse(args.payload)
        print(json.dumps(signal.to_dict(), indent=2))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _cmd_paper_test(args: argparse.Namespace) -> int:
    """Run a quick paper trading simulation."""
    router = SignalRouter(capital=args.capital)
    paper = PaperBroker(initial_balance=args.capital)
    paper.connect()
    router.register_broker(paper)

    test_signals = [
        {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "sl": 41000, "tp": 44000},
        {"ticker": "ETHUSDT", "action": "buy", "price": 2800, "sl": 2700, "tp": 3000},
        {"ticker": "BTCUSDT", "action": "close_long", "price": 43500},
        {"ticker": "ETHUSDT", "action": "close_long", "price": 2950},
    ]

    print(f"📊 Paper Trading Simulation — Capital: ${args.capital:,.2f}\n")

    for sig in test_signals:
        result = router.route(sig)
        status = result.get("status", "?")
        order = result.get("order", {})
        qty = order.get("fill_quantity", 0)
        price = order.get("fill_price", 0)
        print(
            f"  [{status:>8s}] {sig['action']:>12s} {sig['ticker']:>10s} "
            f"qty={qty:.6f} @ ${price:,.2f}"
        )

    stats = paper.get_stats()
    print(f"\n💰 Final Balance: ${stats['current_balance']:,.2f}")
    print(f"📈 Return: {stats['return_pct']}%")
    print(f"🔄 Total Trades: {stats['total_trades']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
