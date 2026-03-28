"""Tests for data models."""

import pytest
from src.models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    Side,
    Signal,
    SignalAction,
)


class TestSignal:
    def test_default_signal(self):
        s = Signal()
        assert s.ticker == ""
        assert s.action == SignalAction.OPEN_LONG
        assert s.side == Side.BUY
        assert s.id != ""

    def test_buy_signal_side(self):
        s = Signal(action=SignalAction.OPEN_LONG)
        assert s.side == Side.BUY

    def test_sell_signal_side(self):
        s = Signal(action=SignalAction.OPEN_SHORT)
        assert s.side == Side.SELL

    def test_close_long_is_sell(self):
        s = Signal(action=SignalAction.CLOSE_LONG)
        assert s.side == Side.SELL

    def test_close_short_is_buy(self):
        s = Signal(action=SignalAction.CLOSE_SHORT)
        assert s.side == Side.BUY

    def test_to_dict(self):
        s = Signal(ticker="BTCUSDT", price=42000.0)
        d = s.to_dict()
        assert d["ticker"] == "BTCUSDT"
        assert d["price"] == 42000.0
        assert "received_at" in d

    def test_unique_ids(self):
        s1 = Signal()
        s2 = Signal()
        assert s1.id != s2.id


class TestOrder:
    def test_default_order(self):
        o = Order()
        assert o.status == OrderStatus.PENDING
        assert not o.is_terminal

    def test_filled_is_terminal(self):
        o = Order(status=OrderStatus.FILLED)
        assert o.is_terminal

    def test_cancelled_is_terminal(self):
        o = Order(status=OrderStatus.CANCELLED)
        assert o.is_terminal

    def test_submitted_is_not_terminal(self):
        o = Order(status=OrderStatus.SUBMITTED)
        assert not o.is_terminal

    def test_pnl_calculation_buy(self):
        o = Order(
            side=Side.BUY,
            price=100.0,
            fill_price=110.0,
            fill_quantity=10.0,
            commission=5.0,
        )
        # (110 - 100) * 10 - 5 = 95
        assert o.pnl == 95.0

    def test_pnl_calculation_sell(self):
        o = Order(
            side=Side.SELL,
            price=100.0,
            fill_price=90.0,
            fill_quantity=10.0,
            commission=5.0,
        )
        # -(90 - 100) * 10 - 5 = 95
        assert o.pnl == 95.0

    def test_pnl_none_without_fill(self):
        o = Order(price=100.0)
        assert o.pnl is None

    def test_to_dict(self):
        o = Order(ticker="ETHUSDT", quantity=5.0)
        d = o.to_dict()
        assert d["ticker"] == "ETHUSDT"
        assert d["quantity"] == 5.0


class TestPosition:
    def test_open_position(self):
        p = Position(ticker="BTCUSDT", quantity=1.0, entry_price=42000.0)
        assert p.is_open
        assert p.notional_value == 42000.0

    def test_closed_position(self):
        p = Position(ticker="BTCUSDT", quantity=0.0)
        assert not p.is_open

    def test_to_dict(self):
        p = Position(ticker="AAPL", quantity=10, entry_price=150.0)
        d = p.to_dict()
        assert d["notional_value"] == 1500.0


class TestEnums:
    def test_side_values(self):
        assert Side.BUY.value == "buy"
        assert Side.SELL.value == "sell"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"

    def test_signal_action_values(self):
        assert SignalAction.OPEN_LONG.value == "open_long"
        assert SignalAction.CLOSE_ALL.value == "close_all"
