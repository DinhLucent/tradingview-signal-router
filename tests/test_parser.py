"""Tests for signal parser."""

import pytest
from src.parser import SignalParser, SignalParseError
from src.models import SignalAction, OrderType


class TestSignalParserJSON:
    def setup_method(self):
        self.parser = SignalParser()

    def test_basic_json_buy(self):
        payload = '{"ticker": "BTCUSDT", "action": "buy", "price": 42000}'
        signal = self.parser.parse(payload)
        assert signal.ticker == "BTCUSDT"
        assert signal.action == SignalAction.OPEN_LONG
        assert signal.price == 42000.0

    def test_basic_json_sell(self):
        payload = '{"ticker": "ETHUSDT", "action": "sell", "price": 2800}'
        signal = self.parser.parse(payload)
        assert signal.ticker == "ETHUSDT"
        assert signal.action == SignalAction.OPEN_SHORT

    def test_json_with_stop_loss(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "sl": 41000}
        signal = self.parser.parse(payload)
        assert signal.stop_loss == 41000.0

    def test_json_with_take_profit(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "tp": 44000}
        signal = self.parser.parse(payload)
        assert signal.take_profit == 44000.0

    def test_json_long_action(self):
        payload = {"ticker": "BTCUSDT", "action": "long", "price": 42000}
        signal = self.parser.parse(payload)
        assert signal.action == SignalAction.OPEN_LONG

    def test_json_short_action(self):
        payload = {"ticker": "BTCUSDT", "action": "short", "price": 42000}
        signal = self.parser.parse(payload)
        assert signal.action == SignalAction.OPEN_SHORT

    def test_json_close_long(self):
        payload = {"ticker": "BTCUSDT", "action": "close_long", "price": 43000}
        signal = self.parser.parse(payload)
        assert signal.action == SignalAction.CLOSE_LONG

    def test_json_close_all(self):
        payload = {"ticker": "BTCUSDT", "action": "close", "price": 43000}
        signal = self.parser.parse(payload)
        assert signal.action == SignalAction.CLOSE_ALL

    def test_json_flatten_action(self):
        payload = {"ticker": "BTCUSDT", "action": "flatten", "price": 43000}
        signal = self.parser.parse(payload)
        assert signal.action == SignalAction.CLOSE_ALL

    def test_json_with_quantity(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "qty": 0.5}
        signal = self.parser.parse(payload)
        assert signal.quantity == 0.5

    def test_json_with_leverage(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "leverage": 5}
        signal = self.parser.parse(payload)
        assert signal.leverage == 5.0

    def test_json_with_exchange(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "exchange": "binance"}
        signal = self.parser.parse(payload)
        assert signal.exchange == "binance"

    def test_json_limit_order(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "order_type": "limit"}
        signal = self.parser.parse(payload)
        assert signal.order_type == OrderType.LIMIT

    def test_json_stop_order(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "order_type": "stop"}
        signal = self.parser.parse(payload)
        assert signal.order_type == OrderType.STOP

    def test_json_symbol_alias(self):
        payload = {"symbol": "AAPL", "action": "buy", "price": 150}
        signal = self.parser.parse(payload)
        assert signal.ticker == "AAPL"

    def test_json_close_field(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "close": 42500}
        signal = self.parser.parse(payload)
        assert signal.price == 42500.0

    def test_json_uppercase_ticker(self):
        payload = {"ticker": "btcusdt", "action": "buy", "price": 42000}
        signal = self.parser.parse(payload)
        assert signal.ticker == "BTCUSDT"


class TestSignalParserText:
    def setup_method(self):
        self.parser = SignalParser()

    def test_text_key_value(self):
        text = "ticker=BTCUSDT action=buy price=42000"
        signal = self.parser.parse(text)
        assert signal.ticker == "BTCUSDT"
        assert signal.action == SignalAction.OPEN_LONG

    def test_text_ticker_action_prefix(self):
        text = "BTCUSDT buy price=42000 sl=41500 tp=43000"
        signal = self.parser.parse(text)
        assert signal.ticker == "BTCUSDT"
        assert signal.action == SignalAction.OPEN_LONG
        assert signal.stop_loss == 41500.0
        assert signal.take_profit == 43000.0

    def test_text_with_qty(self):
        text = "ticker=ETHUSDT action=sell qty=0.5"
        signal = self.parser.parse(text)
        assert signal.quantity == 0.5


class TestSignalParserDict:
    def setup_method(self):
        self.parser = SignalParser()

    def test_dict_payload(self):
        payload = {"ticker": "SOLUSDT", "action": "buy", "price": 100}
        signal = self.parser.parse(payload)
        assert signal.ticker == "SOLUSDT"

    def test_raw_payload_preserved(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "custom": "data"}
        signal = self.parser.parse(payload)
        assert signal.raw_payload["custom"] == "data"


class TestSignalParserEdgeCases:
    def setup_method(self):
        self.parser = SignalParser()

    def test_missing_ticker_non_strict(self):
        payload = {"action": "buy", "price": 42000}
        signal = self.parser.parse(payload)
        assert signal.ticker == "UNKNOWN"

    def test_missing_ticker_strict(self):
        parser = SignalParser(strict_mode=True)
        with pytest.raises(SignalParseError):
            parser.parse({"action": "buy", "price": 42000})

    def test_invalid_payload_type(self):
        with pytest.raises(SignalParseError):
            self.parser.parse(12345)

    def test_safe_float_none(self):
        assert SignalParser._safe_float(None) is None

    def test_safe_float_string(self):
        assert SignalParser._safe_float("42.5") == 42.5

    def test_safe_float_invalid(self):
        assert SignalParser._safe_float("not_a_number") is None

    def test_default_exchange(self):
        parser = SignalParser(default_exchange="binance")
        signal = parser.parse({"ticker": "BTCUSDT", "action": "buy", "price": 42000})
        assert signal.exchange == "binance"

    def test_empty_json_string(self):
        signal = self.parser.parse("{}")
        assert signal.ticker == "UNKNOWN"

    def test_strategy_field(self):
        payload = {"ticker": "BTCUSDT", "action": "buy", "price": 42000, "strategy": "EMA_Cross"}
        signal = self.parser.parse(payload)
        assert signal.strategy == "EMA_Cross"
