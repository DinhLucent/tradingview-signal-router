"""
Core signal routing engine.

Orchestrates the signal lifecycle: parse → validate → size → route → execute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .brokers import BrokerAdapter, PaperBroker
from .models import Order, OrderStatus, Signal
from .parser import SignalParser
from .risk import RiskConfig, RiskManager

logger = logging.getLogger(__name__)


@dataclass
class RouterConfig:
    """Signal router configuration."""

    default_broker: str = "paper"
    enable_risk_checks: bool = True
    enable_paper_mirror: bool = False  # Mirror all trades to paper
    log_signals: bool = True
    max_signal_age_seconds: int = 30
    webhook_secret: str = ""


class SignalRouter:
    """Central routing engine for TradingView signals.

    Pipeline: Receive → Parse → Validate → Size → Route → Execute

    Supports multiple broker adapters, risk management, and
    signal logging for audit trails.
    """

    def __init__(
        self,
        config: Optional[RouterConfig] = None,
        risk_config: Optional[RiskConfig] = None,
        capital: float = 10000.0,
    ):
        self.config = config or RouterConfig()
        self.risk_manager = RiskManager(config=risk_config, capital=capital)
        self.parser = SignalParser()
        self._brokers: Dict[str, BrokerAdapter] = {}
        self._signal_log: List[Dict[str, Any]] = []
        self._order_log: List[Dict[str, Any]] = []
        self._hooks: Dict[str, List[Callable]] = {
            "pre_parse": [],
            "post_parse": [],
            "pre_validate": [],
            "post_validate": [],
            "pre_execute": [],
            "post_execute": [],
        }
        self._stats = {
            "signals_received": 0,
            "signals_accepted": 0,
            "signals_rejected": 0,
            "orders_filled": 0,
            "orders_failed": 0,
        }

    def register_broker(self, broker: BrokerAdapter) -> None:
        """Register a broker adapter for order routing."""
        self._brokers[broker.name] = broker
        logger.info(f"Registered broker: {broker.name}")

    def register_hook(self, event: str, callback: Callable) -> None:
        """Register a lifecycle hook.

        Events: pre_parse, post_parse, pre_validate, post_validate,
                pre_execute, post_execute
        """
        if event in self._hooks:
            self._hooks[event].append(callback)

    def route(
        self,
        payload: Any,
        broker_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route a TradingView webhook payload through the full pipeline.

        Args:
            payload: Raw webhook body (JSON string, dict, or text).
            broker_name: Target broker name. Uses default if not specified.

        Returns:
            Dict with routing result: signal, order, risk check, etc.
        """
        self._stats["signals_received"] += 1
        result: Dict[str, Any] = {"status": "error", "signal": None, "order": None}

        # --- Parse ---
        self._fire_hooks("pre_parse", payload)
        try:
            signal = self.parser.parse(payload)
        except Exception as e:
            result["error"] = f"Parse error: {e}"
            self._stats["signals_rejected"] += 1
            return result

        self._fire_hooks("post_parse", signal)
        result["signal"] = signal.to_dict()

        if self.config.log_signals:
            self._signal_log.append(signal.to_dict())

        # --- Validate ---
        if self.config.enable_risk_checks:
            self._fire_hooks("pre_validate", signal)
            risk_result = self.risk_manager.validate(signal)
            result["risk_check"] = str(risk_result)

            if not risk_result:
                result["status"] = "rejected"
                result["error"] = risk_result.reason
                self._stats["signals_rejected"] += 1
                self._fire_hooks("post_validate", signal, risk_result)
                return result

            self._fire_hooks("post_validate", signal, risk_result)

        # --- Size ---
        quantity = self.risk_manager.calculate_position_size(signal)
        result["quantity"] = quantity

        if quantity <= 0:
            result["status"] = "rejected"
            result["error"] = "Calculated position size is zero"
            self._stats["signals_rejected"] += 1
            return result

        # --- Route to broker ---
        target = broker_name or self.config.default_broker
        broker = self._brokers.get(target)
        if not broker:
            result["status"] = "error"
            result["error"] = f"Broker '{target}' not registered"
            self._stats["signals_rejected"] += 1
            return result

        if not broker.is_connected:
            result["status"] = "error"
            result["error"] = f"Broker '{target}' not connected"
            self._stats["signals_rejected"] += 1
            return result

        # --- Execute ---
        order = broker.create_order_from_signal(signal, quantity)
        self._fire_hooks("pre_execute", signal, order)

        order = broker.submit_order(order)
        result["order"] = order.to_dict()

        if order.status == OrderStatus.FILLED:
            result["status"] = "filled"
            self._stats["signals_accepted"] += 1
            self._stats["orders_filled"] += 1
            self.risk_manager.record_trade(order)
        elif order.status == OrderStatus.REJECTED:
            result["status"] = "rejected"
            result["error"] = order.error_message
            self._stats["orders_failed"] += 1
        else:
            result["status"] = order.status.value
            self._stats["signals_accepted"] += 1

        self._order_log.append(order.to_dict())
        self._fire_hooks("post_execute", signal, order)

        # --- Mirror to paper if enabled ---
        if (
            self.config.enable_paper_mirror
            and target != "paper"
            and "paper" in self._brokers
        ):
            paper = self._brokers["paper"]
            if paper.is_connected:
                mirror_order = paper.create_order_from_signal(signal, quantity)
                mirror_order.price = signal.price
                paper.submit_order(mirror_order)

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return dict(self._stats)

    def get_signal_log(self) -> List[Dict[str, Any]]:
        """Get all logged signals."""
        return list(self._signal_log)

    def get_order_log(self) -> List[Dict[str, Any]]:
        """Get all logged orders."""
        return list(self._order_log)

    def _fire_hooks(self, event: str, *args: Any) -> None:
        """Fire registered hooks for an event."""
        for hook in self._hooks.get(event, []):
            try:
                hook(*args)
            except Exception as e:
                logger.warning(f"Hook error on {event}: {e}")
