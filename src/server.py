"""
Webhook server for receiving TradingView alerts.

Provides HTTP and Flask-compatible endpoints for signal ingestion.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional

from .router import SignalRouter

logger = logging.getLogger(__name__)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for TradingView webhooks."""

    router: Optional[SignalRouter] = None
    webhook_secret: str = ""
    _on_signal: Optional[Callable] = None

    def do_POST(self) -> None:
        """Handle incoming webhook POST requests."""
        if self.path not in ("/webhook", "/signal", "/alert", "/"):
            self._send_response(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        # Verify webhook signature if secret is configured
        if self.webhook_secret:
            signature = self.headers.get("X-Signature", "")
            if not self._verify_signature(raw_body, signature):
                logger.warning("Webhook signature verification failed")
                self._send_response(401, {"error": "Invalid signature"})
                return

        # Parse body
        try:
            body = raw_body.decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = body
        except Exception as e:
            self._send_response(400, {"error": f"Invalid body: {e}"})
            return

        # Route signal
        if self.router is None:
            self._send_response(503, {"error": "Router not initialized"})
            return

        result = self.router.route(payload)

        if self._on_signal:
            self._on_signal(result)

        status_code = 200 if result.get("status") in ("filled", "submitted") else 422
        self._send_response(status_code, result)

    def do_GET(self) -> None:
        """Health check and stats endpoint."""
        if self.path == "/health":
            self._send_response(200, {"status": "ok"})
        elif self.path == "/stats" and self.router:
            self._send_response(200, self.router.get_stats())
        else:
            self._send_response(200, {"service": "tradingview-signal-router", "status": "running"})

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 webhook signature."""
        if not self.webhook_secret:
            return True
        expected = hmac.new(
            self.webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def _send_response(self, status: int, data: Any) -> None:
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = json.dumps(data, default=str)
        self.wfile.write(response.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Route HTTP logs through standard logger."""
        logger.debug(format, *args)


class WebhookServer:
    """Standalone webhook server wrapping HTTPServer.

    Usage:
        server = WebhookServer(router=my_router, port=8080)
        server.start()
    """

    def __init__(
        self,
        router: SignalRouter,
        host: str = "0.0.0.0",
        port: int = 8080,
        webhook_secret: str = "",
        on_signal: Optional[Callable] = None,
    ):
        self.router = router
        self.host = host
        self.port = port
        self.webhook_secret = webhook_secret
        self.on_signal = on_signal
        self._server: Optional[HTTPServer] = None

    def start(self) -> None:
        """Start the webhook server (blocking)."""
        WebhookHandler.router = self.router
        WebhookHandler.webhook_secret = self.webhook_secret
        WebhookHandler._on_signal = self.on_signal

        self._server = HTTPServer((self.host, self.port), WebhookHandler)
        logger.info(f"Webhook server listening on {self.host}:{self.port}")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Webhook server shutting down...")
            self.stop()

    def stop(self) -> None:
        """Stop the webhook server."""
        if self._server:
            self._server.shutdown()
            self._server = None
