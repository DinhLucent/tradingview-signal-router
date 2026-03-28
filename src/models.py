"""
Core data models for trading signals and order management.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class Side(str, Enum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order lifecycle states."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalAction(str, Enum):
    """Parsed signal actions from TradingView."""

    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"
    CLOSE_ALL = "close_all"


@dataclass
class Signal:
    """Parsed TradingView webhook signal."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ticker: str = ""
    action: SignalAction = SignalAction.OPEN_LONG
    price: float = 0.0
    quantity: Optional[float] = None
    order_type: OrderType = OrderType.MARKET
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    leverage: float = 1.0
    exchange: str = ""
    timeframe: str = ""
    strategy: str = ""
    comment: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def side(self) -> Side:
        if self.action in (SignalAction.OPEN_LONG, SignalAction.CLOSE_SHORT):
            return Side.BUY
        return Side.SELL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "action": self.action.value,
            "side": self.side.value,
            "price": self.price,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "leverage": self.leverage,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "received_at": self.received_at.isoformat(),
        }


@dataclass
class Order:
    """Broker order representation with lifecycle tracking."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    signal_id: str = ""
    broker: str = ""
    ticker: str = ""
    side: Side = Side.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: Optional[float] = None
    fill_quantity: float = 0.0
    commission: float = 0.0
    error_message: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_terminal(self) -> bool:
        """Check if order has reached a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def pnl(self) -> Optional[float]:
        """Calculate realized P&L if filled."""
        if self.fill_price is None or self.price is None:
            return None
        diff = self.fill_price - self.price
        if self.side == Side.SELL:
            diff = -diff
        return diff * self.fill_quantity - self.commission

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "broker": self.broker,
            "ticker": self.ticker,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "status": self.status.value,
            "fill_price": self.fill_price,
            "fill_quantity": self.fill_quantity,
            "commission": self.commission,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Position:
    """Active trading position tracker."""

    ticker: str = ""
    side: Side = Side.BUY
    quantity: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    orders: list = field(default_factory=list)

    @property
    def notional_value(self) -> float:
        return self.quantity * self.entry_price

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "notional_value": self.notional_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
        }
