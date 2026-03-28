"""
Broker adapter interface and implementations.

Provides a unified interface for order execution across different
trading platforms with built-in paper trading support.
"""

from __future__ import annotations

import abc
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import Order, OrderStatus, OrderType, Position, Side, Signal

logger = logging.getLogger(__name__)


class BrokerError(Exception):
    """Base exception for broker operations."""

    pass


class BrokerAdapter(abc.ABC):
    """Abstract broker adapter interface.

    All broker implementations must inherit from this class and
    implement the required methods for order execution.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self._connected = False

    @abc.abstractmethod
    def connect(self) -> bool:
        """Establish connection to the broker."""
        ...

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close broker connection."""
        ...

    @abc.abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Submit an order to the broker.

        Args:
            order: The order to submit.

        Returns:
            Updated order with broker response data.
        """
        ...

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> Order:
        """Cancel a pending order."""
        ...

    @abc.abstractmethod
    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        ...

    @abc.abstractmethod
    def get_balance(self) -> float:
        """Get current account balance."""
        ...

    @property
    def is_connected(self) -> bool:
        return self._connected

    def create_order_from_signal(
        self, signal: Signal, quantity: float
    ) -> Order:
        """Create an Order from a Signal and calculated quantity."""
        return Order(
            signal_id=signal.id,
            broker=self.name,
            ticker=signal.ticker,
            side=signal.side,
            order_type=signal.order_type,
            quantity=quantity,
            price=signal.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )


class PaperBroker(BrokerAdapter):
    """Paper trading broker for testing and simulation.

    Simulates order execution with configurable fill behavior.
    Maintains an in-memory order book and position tracker.
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission_rate: float = 0.001,
        slippage_pct: float = 0.0005,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name="paper", config=config)
        self.initial_balance = initial_balance
        self._balance = initial_balance
        self.commission_rate = commission_rate
        self.slippage_pct = slippage_pct
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._trade_log: List[Dict[str, Any]] = []

    def connect(self) -> bool:
        self._connected = True
        logger.info("Paper broker connected")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("Paper broker disconnected")

    def submit_order(self, order: Order) -> Order:
        """Simulate order execution with slippage and commission."""
        if not self._connected:
            order.status = OrderStatus.REJECTED
            order.error_message = "Broker not connected"
            return order

        order.status = OrderStatus.SUBMITTED

        # Simulate fill
        fill_price = order.price or 0.0
        if order.order_type == OrderType.MARKET and fill_price == 0:
            order.status = OrderStatus.REJECTED
            order.error_message = "Market order requires price context"
            return order

        # Apply slippage
        slippage = fill_price * self.slippage_pct
        if order.side == Side.BUY:
            fill_price += slippage
        else:
            fill_price -= slippage

        commission = order.quantity * fill_price * self.commission_rate

        order.fill_price = round(fill_price, 8)
        order.fill_quantity = order.quantity
        order.commission = round(commission, 8)
        order.status = OrderStatus.FILLED
        order.updated_at = datetime.now(timezone.utc)

        # Update balance
        cost = order.quantity * fill_price + commission
        if order.side == Side.BUY:
            self._balance -= cost
        else:
            self._balance += cost - commission

        # Update positions
        self._update_position(order)

        # Record trade
        self._orders[order.id] = order
        self._trade_log.append(order.to_dict())
        logger.info(
            f"Paper fill: {order.side.value} {order.quantity} {order.ticker} "
            f"@ {order.fill_price} (commission: {order.commission})"
        )

        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if not order:
            raise BrokerError(f"Order {order_id} not found")
        if order.is_terminal:
            raise BrokerError(f"Cannot cancel terminal order {order_id}")
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        return order

    def get_positions(self) -> List[Position]:
        return [p for p in self._positions.values() if p.is_open]

    def get_balance(self) -> float:
        return round(self._balance, 2)

    def get_trade_log(self) -> List[Dict[str, Any]]:
        return list(self._trade_log)

    def get_stats(self) -> Dict[str, Any]:
        """Get paper trading performance statistics."""
        total_trades = len(self._trade_log)
        total_pnl = self._balance - self.initial_balance
        winning = [t for t in self._trade_log if (t.get("fill_price", 0) or 0) > 0]

        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.get_balance(),
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "open_positions": len(self.get_positions()),
            "return_pct": round(total_pnl / self.initial_balance * 100, 2)
            if self.initial_balance > 0
            else 0.0,
        }

    def _update_position(self, order: Order) -> None:
        """Update position tracking after a fill."""
        pos = self._positions.get(order.ticker)

        if pos is None:
            self._positions[order.ticker] = Position(
                ticker=order.ticker,
                side=order.side,
                quantity=order.fill_quantity,
                entry_price=order.fill_price or 0.0,
            )
        else:
            if pos.side == order.side:
                # Adding to position
                total_qty = pos.quantity + order.fill_quantity
                if total_qty > 0:
                    pos.entry_price = (
                        pos.entry_price * pos.quantity
                        + (order.fill_price or 0.0) * order.fill_quantity
                    ) / total_qty
                pos.quantity = total_qty
            else:
                # Reducing / closing position
                pos.quantity -= order.fill_quantity
                if pos.quantity <= 0:
                    pos.quantity = 0


class CCXTBroker(BrokerAdapter):
    """CCXT-based broker adapter for crypto exchanges.

    Requires ccxt library to be installed separately.
    Supports any exchange supported by CCXT (Binance, Bybit, etc.)
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        sandbox: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=f"ccxt_{exchange_id}", config=config)
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self._exchange = None

    def connect(self) -> bool:
        try:
            import ccxt  # type: ignore

            exchange_class = getattr(ccxt, self.exchange_id, None)
            if exchange_class is None:
                raise BrokerError(f"Unknown exchange: {self.exchange_id}")

            self._exchange = exchange_class(
                {
                    "apiKey": self.api_key,
                    "secret": self.api_secret,
                    "sandbox": self.sandbox,
                    "enableRateLimit": True,
                    **(self.config or {}),
                }
            )
            self._exchange.load_markets()
            self._connected = True
            logger.info(f"Connected to {self.exchange_id} (sandbox={self.sandbox})")
            return True
        except ImportError:
            raise BrokerError(
                "ccxt is not installed. Run: pip install ccxt"
            )
        except Exception as e:
            raise BrokerError(f"Failed to connect to {self.exchange_id}: {e}")

    def disconnect(self) -> None:
        self._exchange = None
        self._connected = False

    def submit_order(self, order: Order) -> Order:
        if not self._exchange:
            order.status = OrderStatus.REJECTED
            order.error_message = "Exchange not connected"
            return order

        try:
            order.status = OrderStatus.SUBMITTED
            type_map = {
                OrderType.MARKET: "market",
                OrderType.LIMIT: "limit",
                OrderType.STOP: "stop",
                OrderType.STOP_LIMIT: "stop_limit",
            }

            result = self._exchange.create_order(
                symbol=order.ticker,
                type=type_map.get(order.order_type, "market"),
                side=order.side.value,
                amount=order.quantity,
                price=order.price,
            )

            order.id = str(result.get("id", order.id))
            order.status = OrderStatus.FILLED
            order.fill_price = result.get("average", result.get("price"))
            order.fill_quantity = result.get("filled", order.quantity)
            order.commission = result.get("fee", {}).get("cost", 0.0) or 0.0
            order.updated_at = datetime.now(timezone.utc)

            logger.info(
                f"CCXT order filled: {order.side.value} {order.fill_quantity} "
                f"{order.ticker} @ {order.fill_price}"
            )
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            logger.error(f"CCXT order failed: {e}")

        return order

    def cancel_order(self, order_id: str) -> Order:
        if not self._exchange:
            raise BrokerError("Exchange not connected")
        try:
            self._exchange.cancel_order(order_id)
            return Order(id=order_id, status=OrderStatus.CANCELLED)
        except Exception as e:
            raise BrokerError(f"Cancel failed: {e}")

    def get_positions(self) -> List[Position]:
        if not self._exchange:
            return []
        try:
            positions = self._exchange.fetch_positions()
            return [
                Position(
                    ticker=p["symbol"],
                    side=Side.BUY if p.get("side") == "long" else Side.SELL,
                    quantity=abs(float(p.get("contracts", 0))),
                    entry_price=float(p.get("entryPrice", 0)),
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                )
                for p in positions
                if float(p.get("contracts", 0)) != 0
            ]
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    def get_balance(self) -> float:
        if not self._exchange:
            return 0.0
        try:
            balance = self._exchange.fetch_balance()
            return float(balance.get("total", {}).get("USDT", 0))
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0
