"""Tests for signal router."""

import pytest
from src.router import SignalRouter, RouterConfig
from src.risk import RiskConfig
from src.brokers import PaperBroker
from src.models import SignalAction


class TestRouterBasic:
    def setup_method(self):
        self.router = SignalRouter(capital=10000)
        self.paper = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        self.paper.connect()
        self.router.register_broker(self.paper)

    def test_route_buy_signal(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000}
        result = self.router.route(payload)
        assert result["status"] == "filled"
        assert result["order"]["ticker"] == "BTCUSDT"

    def test_route_sell_signal(self):
        payload = {"ticker": "ETHUSDT", "action": "sell", "price": 2800}
        result = self.router.route(payload)
        assert result["status"] == "filled"

    def test_route_close_signal(self):
        payload = {"ticker": "BTCUSDT", "action": "close", "price": 43000}
        result = self.router.route(payload)
        assert result["status"] == "filled"

    def test_route_returns_signal(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000}
        result = self.router.route(payload)
        assert result["signal"]["ticker"] == "BTCUSDT"

    def test_route_returns_quantity(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000}
        result = self.router.route(payload)
        assert result["quantity"] > 0

    def test_route_invalid_broker(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000}
        result = self.router.route(payload, broker_name="nonexistent")
        assert result["status"] == "error"
        assert "not registered" in result["error"]


class TestRouterRiskIntegration:
    def test_risk_rejection(self):
        config = RouterConfig(enable_risk_checks=True)
        risk_config = RiskConfig(max_daily_trades=0)
        router = SignalRouter(config=config, risk_config=risk_config)
        paper = PaperBroker()
        paper.connect()
        router.register_broker(paper)

        result = router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert result["status"] == "rejected"

    def test_risk_disabled(self):
        config = RouterConfig(enable_risk_checks=False)
        router = SignalRouter(config=config, capital=10000)
        paper = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        paper.connect()
        router.register_broker(paper)

        result = router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert result["status"] == "filled"


class TestRouterStats:
    def setup_method(self):
        self.router = SignalRouter(capital=10000)
        self.paper = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        self.paper.connect()
        self.router.register_broker(self.paper)

    def test_stats_tracking(self):
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        stats = self.router.get_stats()
        assert stats["signals_received"] == 1
        assert stats["signals_accepted"] == 1
        assert stats["orders_filled"] == 1

    def test_signal_log(self):
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        log = self.router.get_signal_log()
        assert len(log) == 1

    def test_order_log(self):
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        log = self.router.get_order_log()
        assert len(log) == 1

    def test_multiple_signals(self):
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        self.router.route({"ticker": "ETHUSDT", "action": "buy", "price": 2800})
        stats = self.router.get_stats()
        assert stats["signals_received"] == 2
        assert stats["orders_filled"] == 2


class TestRouterHooks:
    def setup_method(self):
        self.router = SignalRouter(capital=10000)
        self.paper = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        self.paper.connect()
        self.router.register_broker(self.paper)

    def test_post_parse_hook(self):
        signals = []
        self.router.register_hook("post_parse", lambda s: signals.append(s))
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert len(signals) == 1
        assert signals[0].ticker == "BTCUSDT"

    def test_post_execute_hook(self):
        orders = []
        self.router.register_hook("post_execute", lambda s, o: orders.append(o))
        self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert len(orders) == 1

    def test_hook_error_handled(self):
        def bad_hook(s):
            raise ValueError("Hook error!")
        self.router.register_hook("post_parse", bad_hook)
        # Should not crash
        result = self.router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert result["status"] == "filled"


class TestRouterPaperMirror:
    def test_paper_mirror(self):
        config = RouterConfig(default_broker="live", enable_paper_mirror=True, enable_risk_checks=False)
        router = SignalRouter(config=config, capital=10000)

        live = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        live._connected = True
        # Hack name
        live.name = "live"

        paper = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        paper.connect()

        router.register_broker(live)
        router.register_broker(paper)

        router.route({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert len(paper.get_trade_log()) == 1
