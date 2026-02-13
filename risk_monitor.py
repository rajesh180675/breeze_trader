"""
Background risk monitor — polls prices, checks stop-losses, emits alerts.
Runs in a daemon thread. Thread-safe communication via queue.
"""

import threading
import queue
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Alert:
    timestamp: str
    level: str          # INFO, WARNING, CRITICAL
    category: str       # STOP_LOSS, MARGIN, PRICE_MOVE
    message: str
    position_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitoredPosition:
    position_id: str
    stock_code: str
    exchange: str
    expiry: str
    strike: int
    option_type: str
    position_type: str      # short / long
    quantity: int
    avg_price: float
    stop_loss_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    high_water_mark: float = 0.0
    current_price: float = 0.0
    last_update: float = 0.0
    stop_triggered: bool = False


class RiskMonitor:
    """Background thread that monitors positions and generates alerts."""

    def __init__(self, api_client, poll_interval: float = 15.0):
        self._client = api_client
        self._poll_interval = poll_interval
        self._positions: Dict[str, MonitoredPosition] = {}
        self._alerts: queue.Queue = queue.Queue()
        self._alert_history: List[Alert] = []
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    # ─── Position management ──────────────────────────────────

    def add_position(self, position_id: str, stock_code: str, exchange: str,
                     expiry: str, strike: int, option_type: str,
                     position_type: str, quantity: int, avg_price: float):
        with self._lock:
            self._positions[position_id] = MonitoredPosition(
                position_id=position_id, stock_code=stock_code, exchange=exchange,
                expiry=expiry, strike=strike, option_type=option_type,
                position_type=position_type, quantity=quantity, avg_price=avg_price,
                current_price=avg_price, high_water_mark=avg_price
            )

    def remove_position(self, position_id: str):
        with self._lock:
            self._positions.pop(position_id, None)

    def set_stop_loss(self, position_id: str, stop_price: float):
        with self._lock:
            if position_id in self._positions:
                p = self._positions[position_id]
                p.stop_loss_price = stop_price
                p.trailing_stop_pct = None

    def set_trailing_stop(self, position_id: str, trail_pct: float):
        with self._lock:
            if position_id in self._positions:
                p = self._positions[position_id]
                p.trailing_stop_pct = trail_pct
                p.stop_loss_price = None
                p.high_water_mark = p.current_price or p.avg_price

    # ─── Lifecycle ────────────────────────────────────────────

    def start(self):
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="RiskMonitor", daemon=True)
        self._thread.start()
        log.info("Risk monitor started")

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("Risk monitor stopped")

    def is_running(self) -> bool:
        return self._running.is_set()

    # ─── Alert retrieval ──────────────────────────────────────

    def get_alerts(self) -> List[Alert]:
        alerts = []
        while not self._alerts.empty():
            try:
                alerts.append(self._alerts.get_nowait())
            except queue.Empty:
                break
        return alerts

    def get_alert_history(self) -> List[Alert]:
        return list(self._alert_history)

    def get_monitored_summary(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "id": p.position_id, "stock": p.stock_code, "strike": p.strike,
                    "type": p.option_type, "pos": p.position_type, "qty": p.quantity,
                    "avg": p.avg_price, "current": p.current_price,
                    "stop": p.stop_loss_price, "trail_pct": p.trailing_stop_pct,
                    "triggered": p.stop_triggered
                }
                for p in self._positions.values()
            ]

    # ─── Loop ─────────────────────────────────────────────────

    def _loop(self):
        while self._running.is_set():
            try:
                self._check_all()
            except Exception as e:
                log.error(f"Monitor loop error: {e}")
            for _ in range(int(self._poll_interval * 10)):
                if not self._running.is_set():
                    break
                time.sleep(0.1)

    def _check_all(self):
        with self._lock:
            positions = list(self._positions.values())
        for pos in positions:
            if pos.stop_triggered:
                continue
            self._update_price(pos)
            self._check_stop(pos)

    def _update_price(self, pos: MonitoredPosition):
        try:
            resp = self._client.get_quotes(
                pos.stock_code, pos.exchange, pos.expiry, pos.strike, pos.option_type
            )
            if resp.get("success"):
                from helpers import APIResponse, safe_float
                items = APIResponse(resp).items
                if items:
                    ltp = safe_float(items[0].get("ltp", 0))
                    if ltp > 0:
                        pos.current_price = ltp
                        pos.last_update = time.time()
                        if pos.position_type == "short":
                            if ltp < pos.high_water_mark or pos.high_water_mark <= 0:
                                pos.high_water_mark = ltp
                        else:
                            if ltp > pos.high_water_mark:
                                pos.high_water_mark = ltp
        except Exception as e:
            log.debug(f"Price update failed {pos.position_id}: {e}")

    def _check_stop(self, pos: MonitoredPosition):
        if pos.current_price <= 0:
            return
        triggered = False
        reason = ""

        if pos.stop_loss_price is not None:
            if pos.position_type == "short" and pos.current_price >= pos.stop_loss_price:
                triggered = True
                reason = f"Fixed stop hit at ₹{pos.stop_loss_price:.2f}"
            elif pos.position_type == "long" and pos.current_price <= pos.stop_loss_price:
                triggered = True
                reason = f"Fixed stop hit at ₹{pos.stop_loss_price:.2f}"

        elif pos.trailing_stop_pct and pos.trailing_stop_pct > 0 and pos.high_water_mark > 0:
            if pos.position_type == "short":
                trail_level = pos.high_water_mark * (1 + pos.trailing_stop_pct)
                if pos.current_price >= trail_level:
                    triggered = True
                    reason = (f"Trailing stop: low ₹{pos.high_water_mark:.2f}, "
                              f"trail {pos.trailing_stop_pct * 100:.0f}%, trigger ₹{trail_level:.2f}")
            else:
                trail_level = pos.high_water_mark * (1 - pos.trailing_stop_pct)
                if pos.current_price <= trail_level:
                    triggered = True
                    reason = (f"Trailing stop: high ₹{pos.high_water_mark:.2f}, "
                              f"trail {pos.trailing_stop_pct * 100:.0f}%, trigger ₹{trail_level:.2f}")

        if triggered:
            pos.stop_triggered = True
            alert = Alert(
                timestamp=datetime.now().strftime("%H:%M:%S"),
                level="CRITICAL", category="STOP_LOSS",
                message=f"🚨 {pos.stock_code} {pos.strike} {pos.option_type}: {reason}. Current: ₹{pos.current_price:.2f}",
                position_id=pos.position_id,
                data={"current": pos.current_price, "avg": pos.avg_price}
            )
            self._alerts.put(alert)
            self._alert_history.append(alert)
            if len(self._alert_history) > 50:
                self._alert_history = self._alert_history[-50:]
            log.warning(f"STOP TRIGGERED: {alert.message}")
