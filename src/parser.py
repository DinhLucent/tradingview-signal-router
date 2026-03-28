"""
TradingView webhook signal parser.

Handles multiple payload formats:
- JSON payloads from TradingView alerts
- Plain text alerts with key=value format  
- Custom Pine Script alert messages
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from .models import OrderType, Signal, SignalAction

logger = logging.getLogger(__name__)

# Action keyword mapping (case-insensitive)
_ACTION_MAP: Dict[str, SignalAction] = {
    "buy": SignalAction.OPEN_LONG,
    "long": SignalAction.OPEN_LONG,
    "open_long": SignalAction.OPEN_LONG,
    "enter_long": SignalAction.OPEN_LONG,
    "sell": SignalAction.OPEN_SHORT,
    "short": SignalAction.OPEN_SHORT,
    "open_short": SignalAction.OPEN_SHORT,
    "enter_short": SignalAction.OPEN_SHORT,
    "close_long": SignalAction.CLOSE_LONG,
    "exit_long": SignalAction.CLOSE_LONG,
    "close_short": SignalAction.CLOSE_SHORT,
    "exit_short": SignalAction.CLOSE_SHORT,
    "close": SignalAction.CLOSE_ALL,
    "close_all": SignalAction.CLOSE_ALL,
    "flatten": SignalAction.CLOSE_ALL,
    "exit": SignalAction.CLOSE_ALL,
}

_ORDER_TYPE_MAP: Dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP_LIMIT,
    "stop-limit": OrderType.STOP_LIMIT,
}


class SignalParseError(Exception):
    """Raised when a signal cannot be parsed."""

    pass


class SignalParser:
    """Parse TradingView webhook payloads into Signal objects."""

    def __init__(
        self,
        default_exchange: str = "",
        strict_mode: bool = False,
    ):
        self.default_exchange = default_exchange
        self.strict_mode = strict_mode

    def parse(self, payload: Any) -> Signal:
        """Parse a webhook payload into a Signal.

        Accepts JSON string, dict, or plain text.

        Args:
            payload: Raw webhook body content.

        Returns:
            Parsed Signal object.

        Raises:
            SignalParseError: If parsing fails in strict mode.
        """
        if isinstance(payload, str):
            payload = payload.strip()
            # Try JSON first
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    return self._parse_dict(data)
            except json.JSONDecodeError:
                pass
            # Fall back to key=value text parsing
            return self._parse_text(payload)

        if isinstance(payload, dict):
            return self._parse_dict(payload)

        raise SignalParseError(f"Unsupported payload type: {type(payload)}")

    def _parse_dict(self, data: Dict[str, Any]) -> Signal:
        """Parse a dictionary payload."""
        ticker = self._extract_ticker(data)
        action = self._extract_action(data)
        if ticker is None or action is None:
            if self.strict_mode:
                raise SignalParseError(
                    f"Missing required fields: ticker={ticker}, action={action}"
                )
            ticker = ticker or "UNKNOWN"
            action = action or SignalAction.OPEN_LONG

        signal = Signal(
            ticker=ticker.upper(),
            action=action,
            price=self._safe_float(data.get("price", data.get("close", 0))),
            quantity=self._safe_float(data.get("quantity", data.get("qty"))),
            order_type=self._extract_order_type(data),
            stop_loss=self._safe_float(
                data.get("stop_loss", data.get("sl", data.get("stoploss")))
            ),
            take_profit=self._safe_float(
                data.get("take_profit", data.get("tp", data.get("takeprofit")))
            ),
            leverage=self._safe_float(data.get("leverage", 1.0)) or 1.0,
            exchange=str(
                data.get("exchange", self.default_exchange)
            ),
            timeframe=str(data.get("timeframe", data.get("interval", ""))),
            strategy=str(data.get("strategy", data.get("strategy_name", ""))),
            comment=str(data.get("comment", data.get("message", ""))),
            raw_payload=data,
        )
        logger.debug(f"Parsed signal: {signal.id} {signal.ticker} {signal.action.value}")
        return signal

    def _parse_text(self, text: str) -> Signal:
        """Parse a plain text alert message.

        Supports formats like:
            BTCUSDT buy price=42000 sl=41500 tp=43000
            ticker=ETHUSDT action=sell qty=0.5
        """
        data: Dict[str, str] = {}

        # Extract key=value pairs
        for match in re.finditer(r"(\w+)\s*=\s*([^\s,]+)", text):
            data[match.group(1).lower()] = match.group(2)

        # Try to extract ticker and action from the beginning
        tokens = text.split()
        if tokens and not data.get("ticker"):
            # First token might be ticker
            if not any(tokens[0].lower() == k for k in _ACTION_MAP):
                data.setdefault("ticker", tokens[0])
                tokens = tokens[1:]

        if tokens and not data.get("action"):
            for token in tokens:
                if token.lower() in _ACTION_MAP:
                    data["action"] = token
                    break

        return self._parse_dict(data)

    def _extract_ticker(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract ticker/symbol from common field names."""
        for key in ("ticker", "symbol", "pair", "instrument", "contract"):
            val = data.get(key)
            if val:
                return str(val).strip()
        return None

    def _extract_action(self, data: Dict[str, Any]) -> Optional[SignalAction]:
        """Extract trading action from common field names."""
        for key in ("action", "side", "direction", "order", "type", "signal"):
            val = data.get(key)
            if val:
                mapped = _ACTION_MAP.get(str(val).lower().strip())
                if mapped:
                    return mapped
        return None

    def _extract_order_type(self, data: Dict[str, Any]) -> OrderType:
        """Extract order type, defaulting to MARKET."""
        for key in ("order_type", "ordertype", "ord_type"):
            val = data.get(key)
            if val:
                mapped = _ORDER_TYPE_MAP.get(str(val).lower().strip())
                if mapped:
                    return mapped
        return OrderType.MARKET

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert a value to float."""
        if value is None:
            return None
        try:
            result = float(value)
            return result if result == result else None  # NaN check
        except (ValueError, TypeError):
            return None
