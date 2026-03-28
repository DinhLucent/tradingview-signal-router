"""
Risk management engine for position sizing and signal validation.

Enforces configurable risk limits before signals reach broker execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import Order, Position, Signal, Side

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration."""

    max_position_size: float = 10000.0
    max_open_positions: int = 5
    max_daily_loss: float = 500.0
    max_daily_trades: int = 50
    max_leverage: float = 10.0
    risk_per_trade_pct: float = 2.0  # % of capital risked per trade
    require_stop_loss: bool = False
    min_risk_reward_ratio: float = 0.0  # 0 = disabled
    allowed_tickers: Optional[List[str]] = None
    blocked_tickers: Optional[List[str]] = None
    max_order_value: float = 50000.0


@dataclass
class RiskState:
    """Tracks daily risk metrics."""

    daily_loss: float = 0.0
    daily_trades: int = 0
    open_positions: Dict[str, Position] = field(default_factory=dict)

    def reset_daily(self) -> None:
        self.daily_loss = 0.0
        self.daily_trades = 0


class RiskCheckResult:
    """Result of a risk validation check."""

    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "REJECT"
        return f"RiskCheck({status}: {self.reason})"


class RiskManager:
    """Pre-trade risk validation engine.

    Validates signals against configurable risk parameters before
    they are routed to broker adapters for execution.
    """

    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        capital: float = 10000.0,
    ):
        self.config = config or RiskConfig()
        self.capital = capital
        self.state = RiskState()

    def validate(self, signal: Signal) -> RiskCheckResult:
        """Run all risk checks against a signal.

        Args:
            signal: The parsed trading signal.

        Returns:
            RiskCheckResult indicating pass/fail with reason.
        """
        checks = [
            self._check_ticker_allowed,
            self._check_daily_trade_limit,
            self._check_daily_loss_limit,
            self._check_max_positions,
            self._check_leverage,
            self._check_stop_loss,
            self._check_risk_reward,
            self._check_order_value,
        ]

        for check_fn in checks:
            result = check_fn(signal)
            if not result:
                logger.warning(f"Risk check failed for {signal.id}: {result.reason}")
                return result

        return RiskCheckResult(True, "All risk checks passed")

    def calculate_position_size(
        self,
        signal: Signal,
        account_balance: Optional[float] = None,
    ) -> float:
        """Calculate optimal position size using risk-based sizing.

        Uses the configured risk_per_trade_pct to determine how many
        units to trade based on the distance to stop loss.

        Args:
            signal: The trading signal with price and stop loss.
            account_balance: Override account balance. Uses self.capital if None.

        Returns:
            Calculated position size (quantity).
        """
        balance = account_balance or self.capital

        if signal.quantity is not None and signal.quantity > 0:
            return min(signal.quantity, self.config.max_position_size)

        risk_amount = balance * (self.config.risk_per_trade_pct / 100.0)

        if signal.stop_loss and signal.price > 0:
            risk_per_unit = abs(signal.price - signal.stop_loss)
            if risk_per_unit > 0:
                size = risk_amount / risk_per_unit
                return min(size, self.config.max_position_size)

        # Fallback: risk_amount / price
        if signal.price > 0:
            return min(risk_amount / signal.price, self.config.max_position_size)

        return 0.0

    def record_trade(self, order: Order) -> None:
        """Record a completed trade for risk state tracking."""
        self.state.daily_trades += 1
        if order.pnl is not None and order.pnl < 0:
            self.state.daily_loss += abs(order.pnl)

    def record_position(self, position: Position) -> None:
        """Track an open position."""
        if position.is_open:
            self.state.open_positions[position.ticker] = position
        else:
            self.state.open_positions.pop(position.ticker, None)

    def _check_ticker_allowed(self, signal: Signal) -> RiskCheckResult:
        cfg = self.config
        if cfg.allowed_tickers and signal.ticker not in cfg.allowed_tickers:
            return RiskCheckResult(False, f"Ticker {signal.ticker} not in allowed list")
        if cfg.blocked_tickers and signal.ticker in cfg.blocked_tickers:
            return RiskCheckResult(False, f"Ticker {signal.ticker} is blocked")
        return RiskCheckResult(True, "Ticker allowed")

    def _check_daily_trade_limit(self, signal: Signal) -> RiskCheckResult:
        if self.state.daily_trades >= self.config.max_daily_trades:
            return RiskCheckResult(
                False, f"Daily trade limit reached ({self.config.max_daily_trades})"
            )
        return RiskCheckResult(True, "Within daily trade limit")

    def _check_daily_loss_limit(self, signal: Signal) -> RiskCheckResult:
        if self.state.daily_loss >= self.config.max_daily_loss:
            return RiskCheckResult(
                False, f"Daily loss limit reached (${self.config.max_daily_loss})"
            )
        return RiskCheckResult(True, "Within daily loss limit")

    def _check_max_positions(self, signal: Signal) -> RiskCheckResult:
        if len(self.state.open_positions) >= self.config.max_open_positions:
            # Allow closing signals even when at max positions
            if signal.action.value.startswith("close"):
                return RiskCheckResult(True, "Closing signal allowed at max positions")
            return RiskCheckResult(
                False, f"Max open positions reached ({self.config.max_open_positions})"
            )
        return RiskCheckResult(True, "Within position limit")

    def _check_leverage(self, signal: Signal) -> RiskCheckResult:
        if signal.leverage > self.config.max_leverage:
            return RiskCheckResult(
                False, f"Leverage {signal.leverage}x exceeds max {self.config.max_leverage}x"
            )
        return RiskCheckResult(True, "Leverage within limit")

    def _check_stop_loss(self, signal: Signal) -> RiskCheckResult:
        if self.config.require_stop_loss and signal.stop_loss is None:
            if not signal.action.value.startswith("close"):
                return RiskCheckResult(False, "Stop loss required but not provided")
        return RiskCheckResult(True, "Stop loss check passed")

    def _check_risk_reward(self, signal: Signal) -> RiskCheckResult:
        min_rr = self.config.min_risk_reward_ratio
        if min_rr <= 0 or signal.stop_loss is None or signal.take_profit is None:
            return RiskCheckResult(True, "Risk/reward check skipped")

        if signal.price <= 0:
            return RiskCheckResult(True, "No price for R:R calculation")

        risk = abs(signal.price - signal.stop_loss)
        reward = abs(signal.take_profit - signal.price)

        if risk == 0:
            return RiskCheckResult(False, "Zero risk distance")

        rr = reward / risk
        if rr < min_rr:
            return RiskCheckResult(
                False, f"Risk:Reward {rr:.2f} below minimum {min_rr:.2f}"
            )
        return RiskCheckResult(True, f"Risk:Reward {rr:.2f} acceptable")

    def _check_order_value(self, signal: Signal) -> RiskCheckResult:
        if signal.quantity and signal.price:
            value = signal.quantity * signal.price
            if value > self.config.max_order_value:
                return RiskCheckResult(
                    False, f"Order value ${value:.2f} exceeds max ${self.config.max_order_value}"
                )
        return RiskCheckResult(True, "Order value within limit")
