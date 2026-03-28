"""Tests for broker adapters."""

import pytest
from src.brokers import PaperBroker, BrokerError
from src.models import Order, OrderStatus, OrderType, Side, Signal, SignalAction


class TestPaperBrokerConnection:
    def test_connect(self):
        broker = PaperBroker()
        assert not broker.is_connected
        broker.connect()
        assert broker.is_connected

    def test_disconnect(self):
        broker = PaperBroker()
        broker.connect()
        broker.disconnect()
        assert not broker.is_connected


class TestPaperBrokerOrders:
    def setup_method(self):
        self.broker = PaperBroker(initial_balance=10000, commission_rate=0.001, slippage_pct=0)
        self.broker.connect()

    def test_submit_market_buy(self):
        order = Order(
            ticker="BTCUSDT",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=42000,
        )
        result = self.broker.submit_order(order)
        assert result.status == OrderStatus.FILLED
        assert result.fill_price == 42000.0
        assert result.fill_quantity == 0.1
        assert result.commission > 0

    def test_submit_market_sell(self):
        order = Order(
            ticker="BTCUSDT",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=42000,
        )
        result = self.broker.submit_order(order)
        assert result.status == OrderStatus.FILLED

    def test_reject_when_disconnected(self):
        broker = PaperBroker()
        order = Order(ticker="BTCUSDT", side=Side.BUY, quantity=0.1, price=42000)
        result = broker.submit_order(order)
        assert result.status == OrderStatus.REJECTED

    def test_reject_no_price(self):
        order = Order(
            ticker="BTCUSDT",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=0,
        )
        result = self.broker.submit_order(order)
        assert result.status == OrderStatus.REJECTED

    def test_slippage_applied(self):
        broker = PaperBroker(slippage_pct=0.01)  # 1% slippage
        broker.connect()
        order = Order(ticker="BTCUSDT", side=Side.BUY, quantity=0.1, price=100)
        result = broker.submit_order(order)
        assert result.fill_price == 101.0  # 100 + 1%

    def test_slippage_sell_direction(self):
        broker = PaperBroker(slippage_pct=0.01)
        broker.connect()
        order = Order(ticker="BTCUSDT", side=Side.SELL, quantity=0.1, price=100)
        result = broker.submit_order(order)
        assert result.fill_price == 99.0  # 100 - 1%


class TestPaperBrokerBalance:
    def setup_method(self):
        self.broker = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        self.broker.connect()

    def test_balance_decreases_on_buy(self):
        order = Order(ticker="BTCUSDT", side=Side.BUY, quantity=1, price=1000)
        self.broker.submit_order(order)
        assert self.broker.get_balance() == 9000

    def test_balance_increases_on_sell(self):
        order = Order(ticker="BTCUSDT", side=Side.SELL, quantity=1, price=1000)
        self.broker.submit_order(order)
        assert self.broker.get_balance() == 11000

    def test_initial_balance(self):
        assert self.broker.get_balance() == 10000


class TestPaperBrokerPositions:
    def setup_method(self):
        self.broker = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        self.broker.connect()

    def test_position_created_on_buy(self):
        order = Order(ticker="BTCUSDT", side=Side.BUY, quantity=0.5, price=42000)
        self.broker.submit_order(order)
        positions = self.broker.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "BTCUSDT"
        assert positions[0].quantity == 0.5

    def test_position_closed(self):
        self.broker.submit_order(Order(ticker="BTCUSDT", side=Side.BUY, quantity=1, price=100))
        self.broker.submit_order(Order(ticker="BTCUSDT", side=Side.SELL, quantity=1, price=110))
        positions = self.broker.get_positions()
        assert len(positions) == 0

    def test_position_partial_close(self):
        self.broker.submit_order(Order(ticker="BTCUSDT", side=Side.BUY, quantity=2, price=100))
        self.broker.submit_order(Order(ticker="BTCUSDT", side=Side.SELL, quantity=1, price=110))
        positions = self.broker.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 1


class TestPaperBrokerCancelOrder:
    def setup_method(self):
        self.broker = PaperBroker()
        self.broker.connect()

    def test_cancel_filled_raises(self):
        order = Order(ticker="BTCUSDT", side=Side.BUY, quantity=0.1, price=42000)
        filled = self.broker.submit_order(order)
        with pytest.raises(BrokerError):
            self.broker.cancel_order(filled.id)

    def test_cancel_unknown_raises(self):
        with pytest.raises(BrokerError):
            self.broker.cancel_order("unknown_id")


class TestPaperBrokerStats:
    def test_stats(self):
        broker = PaperBroker(initial_balance=10000)
        broker.connect()
        stats = broker.get_stats()
        assert stats["initial_balance"] == 10000
        assert stats["current_balance"] == 10000
        assert stats["total_pnl"] == 0
        assert stats["total_trades"] == 0

    def test_trade_log(self):
        broker = PaperBroker(initial_balance=10000, commission_rate=0, slippage_pct=0)
        broker.connect()
        broker.submit_order(Order(ticker="BTCUSDT", side=Side.BUY, quantity=0.1, price=42000))
        log = broker.get_trade_log()
        assert len(log) == 1
        assert log[0]["ticker"] == "BTCUSDT"


class TestPaperBrokerFromSignal:
    def test_create_order_from_signal(self):
        broker = PaperBroker()
        signal = Signal(
            ticker="ETHUSDT",
            action=SignalAction.OPEN_LONG,
            price=2800,
            stop_loss=2700,
            take_profit=3000,
        )
        order = broker.create_order_from_signal(signal, quantity=1.0)
        assert order.ticker == "ETHUSDT"
        assert order.side == Side.BUY
        assert order.quantity == 1.0
        assert order.stop_loss == 2700
        assert order.take_profit == 3000
        assert order.signal_id == signal.id
