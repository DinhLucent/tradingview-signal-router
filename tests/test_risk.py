"""Tests for risk management engine."""

import pytest
from src.risk import RiskConfig, RiskManager, RiskCheckResult, RiskState
from src.models import Order, OrderStatus, Position, Side, Signal, SignalAction


class TestRiskCheckResult:
    def test_pass_result(self):
        r = RiskCheckResult(True, "OK")
        assert r.passed
        assert bool(r)

    def test_fail_result(self):
        r = RiskCheckResult(False, "Bad")
        assert not r.passed
        assert not bool(r)

    def test_repr(self):
        assert "PASS" in repr(RiskCheckResult(True))
        assert "REJECT" in repr(RiskCheckResult(False, "reason"))


class TestRiskManagerBasic:
    def setup_method(self):
        self.rm = RiskManager(capital=10000)

    def test_valid_signal_passes(self):
        signal = Signal(ticker="BTCUSDT", price=42000, action=SignalAction.OPEN_LONG)
        result = self.rm.validate(signal)
        assert result.passed

    def test_position_sizing_with_stop_loss(self):
        signal = Signal(ticker="BTCUSDT", price=42000, stop_loss=41000)
        size = self.rm.calculate_position_size(signal)
        # risk = 10000 * 0.02 = 200, risk_per_unit = 1000, size = 0.2
        assert abs(size - 0.2) < 0.001

    def test_position_sizing_without_stop_loss(self):
        signal = Signal(ticker="BTCUSDT", price=42000)
        size = self.rm.calculate_position_size(signal)
        # risk = 200 / 42000 ≈ 0.00476
        assert size > 0
        assert size < 1

    def test_position_sizing_with_explicit_quantity(self):
        signal = Signal(ticker="BTCUSDT", price=42000, quantity=0.5)
        size = self.rm.calculate_position_size(signal)
        assert size == 0.5

    def test_position_sizing_capped(self):
        signal = Signal(ticker="BTCUSDT", price=42000, quantity=999999)
        rm = RiskManager(config=RiskConfig(max_position_size=100))
        size = rm.calculate_position_size(signal)
        assert size == 100

    def test_position_sizing_zero_price(self):
        signal = Signal(ticker="BTCUSDT", price=0)
        size = self.rm.calculate_position_size(signal)
        assert size == 0.0


class TestRiskManagerTickerFilter:
    def test_allowed_tickers(self):
        config = RiskConfig(allowed_tickers=["BTCUSDT", "ETHUSDT"])
        rm = RiskManager(config=config)

        ok = rm.validate(Signal(ticker="BTCUSDT", price=42000))
        assert ok.passed

        nok = rm.validate(Signal(ticker="XRPUSDT", price=0.5))
        assert not nok.passed

    def test_blocked_tickers(self):
        config = RiskConfig(blocked_tickers=["DOGEUSD"])
        rm = RiskManager(config=config)

        nok = rm.validate(Signal(ticker="DOGEUSD", price=0.1))
        assert not nok.passed

        ok = rm.validate(Signal(ticker="BTCUSDT", price=42000))
        assert ok.passed


class TestRiskManagerLimits:
    def test_daily_trade_limit(self):
        config = RiskConfig(max_daily_trades=2)
        rm = RiskManager(config=config)
        rm.state.daily_trades = 2

        result = rm.validate(Signal(ticker="BTCUSDT", price=42000))
        assert not result.passed
        assert "daily trade limit" in result.reason.lower()

    def test_daily_loss_limit(self):
        config = RiskConfig(max_daily_loss=100)
        rm = RiskManager(config=config)
        rm.state.daily_loss = 100

        result = rm.validate(Signal(ticker="BTCUSDT", price=42000))
        assert not result.passed

    def test_max_positions(self):
        config = RiskConfig(max_open_positions=1)
        rm = RiskManager(config=config)
        rm.state.open_positions["ETH"] = Position(ticker="ETH", quantity=1)

        result = rm.validate(Signal(ticker="BTCUSDT", price=42000, action=SignalAction.OPEN_LONG))
        assert not result.passed

    def test_close_allowed_at_max_positions(self):
        config = RiskConfig(max_open_positions=1)
        rm = RiskManager(config=config)
        rm.state.open_positions["ETH"] = Position(ticker="ETH", quantity=1)

        result = rm.validate(Signal(ticker="ETH", price=42000, action=SignalAction.CLOSE_LONG))
        assert result.passed

    def test_leverage_limit(self):
        config = RiskConfig(max_leverage=5)
        rm = RiskManager(config=config)

        nok = rm.validate(Signal(ticker="BTCUSDT", price=42000, leverage=10))
        assert not nok.passed

        ok = rm.validate(Signal(ticker="BTCUSDT", price=42000, leverage=3))
        assert ok.passed


class TestRiskManagerStopLoss:
    def test_require_stop_loss(self):
        config = RiskConfig(require_stop_loss=True)
        rm = RiskManager(config=config)

        nok = rm.validate(Signal(ticker="BTCUSDT", price=42000, action=SignalAction.OPEN_LONG))
        assert not nok.passed

        ok = rm.validate(Signal(ticker="BTCUSDT", price=42000, stop_loss=41000, action=SignalAction.OPEN_LONG))
        assert ok.passed

    def test_stop_loss_not_required_for_close(self):
        config = RiskConfig(require_stop_loss=True)
        rm = RiskManager(config=config)

        result = rm.validate(Signal(ticker="BTCUSDT", price=42000, action=SignalAction.CLOSE_LONG))
        assert result.passed


class TestRiskReward:
    def test_risk_reward_ratio(self):
        config = RiskConfig(min_risk_reward_ratio=2.0)
        rm = RiskManager(config=config)

        # Good R:R (3:1)
        ok = rm.validate(Signal(ticker="BTCUSDT", price=42000, stop_loss=41000, take_profit=45000))
        assert ok.passed

        # Bad R:R (0.5:1)
        nok = rm.validate(Signal(ticker="BTCUSDT", price=42000, stop_loss=41000, take_profit=42500))
        assert not nok.passed

    def test_risk_reward_disabled(self):
        config = RiskConfig(min_risk_reward_ratio=0)
        rm = RiskManager(config=config)
        result = rm.validate(Signal(ticker="BTCUSDT", price=42000, stop_loss=41500, take_profit=42100))
        assert result.passed


class TestRiskState:
    def test_reset_daily(self):
        state = RiskState(daily_loss=500, daily_trades=20)
        state.reset_daily()
        assert state.daily_loss == 0.0
        assert state.daily_trades == 0

    def test_record_trade(self):
        rm = RiskManager()
        order = Order(side=Side.BUY, price=100, fill_price=90, fill_quantity=10, commission=5)
        rm.record_trade(order)
        assert rm.state.daily_trades == 1

    def test_record_position(self):
        rm = RiskManager()
        pos = Position(ticker="BTCUSDT", quantity=1)
        rm.record_position(pos)
        assert "BTCUSDT" in rm.state.open_positions

    def test_remove_closed_position(self):
        rm = RiskManager()
        pos = Position(ticker="BTCUSDT", quantity=0)
        rm.state.open_positions["BTCUSDT"] = Position(ticker="BTCUSDT", quantity=1)
        rm.record_position(pos)
        assert "BTCUSDT" not in rm.state.open_positions


class TestOrderValue:
    def test_max_order_value(self):
        config = RiskConfig(max_order_value=1000)
        rm = RiskManager(config=config)

        nok = rm.validate(Signal(ticker="BTCUSDT", price=42000, quantity=1))
        assert not nok.passed

        ok = rm.validate(Signal(ticker="BTCUSDT", price=10, quantity=5))
        assert ok.passed
