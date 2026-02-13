"""
SQLite persistence — trade logs, activity, state snapshots.
Survives browser refresh, crash, session timeout.
Zero dependencies on Streamlit or other app modules.
"""

import sqlite3
import json
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

log = logging.getLogger(__name__)

DB_PATH = Path("data/breeze_trader.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    timestamp TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    exchange TEXT NOT NULL,
    strike INTEGER,
    option_type TEXT,
    expiry TEXT,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    order_type TEXT,
    status TEXT DEFAULT 'executed',
    notes TEXT
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    severity TEXT DEFAULT 'INFO'
);
CREATE TABLE IF NOT EXISTS state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    order_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
"""


class TradeDB:
    """Thread-safe singleton SQLite persistence."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(DB_PATH)
        self._local = threading.local()
        self._init_schema()
        self._initialized = True
        log.info(f"TradeDB ready: {self._db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    @contextmanager
    def _tx(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ─── Trades ───────────────────────────────────────────────

    def log_trade(self, stock_code: str, exchange: str, strike: int,
                  option_type: str, expiry: str, action: str,
                  quantity: int, price: float, order_type: str = "market",
                  trade_id: str = "", notes: str = "") -> bool:
        try:
            if not trade_id:
                trade_id = f"{stock_code}_{strike}_{action}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            with self._tx() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO trades
                    (trade_id, timestamp, stock_code, exchange, strike,
                     option_type, expiry, action, quantity, price, order_type, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (trade_id, datetime.now().isoformat(), stock_code, exchange,
                      strike, option_type, expiry, action, quantity, price, order_type, notes))
            return True
        except Exception as e:
            log.error(f"log_trade failed: {e}")
            return False

    def get_trades(self, limit: int = 100, stock_code: str = "") -> List[Dict]:
        try:
            conn = self._get_conn()
            q = "SELECT * FROM trades WHERE 1=1"
            params: list = []
            if stock_code:
                q += " AND stock_code = ?"
                params.append(stock_code)
            q += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        except Exception as e:
            log.error(f"get_trades failed: {e}")
            return []

    def get_trade_summary(self) -> Dict:
        try:
            conn = self._get_conn()
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN action='sell' THEN quantity*price ELSE 0 END) as sold,
                       SUM(CASE WHEN action='buy' THEN quantity*price ELSE 0 END) as bought
                FROM trades
            """).fetchone()
            return dict(row) if row else {}
        except Exception:
            return {}

    # ─── Activity ─────────────────────────────────────────────

    def log_activity(self, action: str, detail: str = "", severity: str = "INFO") -> bool:
        try:
            conn = self._get_conn()
            conn.execute("INSERT INTO activity_log (timestamp, action, detail, severity) VALUES (?,?,?,?)",
                         (datetime.now().isoformat(), action, detail, severity))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"log_activity failed: {e}")
            return False

    def get_activities(self, limit: int = 100) -> List[Dict]:
        try:
            conn = self._get_conn()
            return [dict(r) for r in conn.execute(
                "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()]
        except Exception:
            return []

    # ─── State snapshots ──────────────────────────────────────

    def save_state(self, state: Dict) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("INSERT INTO state_snapshots (timestamp, state_json) VALUES (?,?)",
                         (datetime.now().isoformat(), json.dumps(state, default=str)))
            conn.execute("""
                DELETE FROM state_snapshots WHERE id NOT IN
                (SELECT id FROM state_snapshots ORDER BY timestamp DESC LIMIT 5)
            """)
            conn.commit()
            return True
        except Exception:
            return False

    def load_state(self) -> Optional[Dict]:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT state_json FROM state_snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return json.loads(row['state_json']) if row else None
        except Exception:
            return None

    # ─── Idempotency ──────────────────────────────────────────

    def check_idempotency(self, key: str) -> Optional[str]:
        try:
            conn = self._get_conn()
            cutoff = time.time() - 300
            conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,))
            conn.commit()
            row = conn.execute("SELECT order_id FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
            return row['order_id'] if row else None
        except Exception:
            return None

    def save_idempotency(self, key: str, order_id: str) -> None:
        try:
            conn = self._get_conn()
            conn.execute("INSERT OR REPLACE INTO idempotency_keys (key, order_id, created_at) VALUES (?,?,?)",
                         (key, order_id, time.time()))
            conn.commit()
        except Exception as e:
            log.error(f"save_idempotency failed: {e}")
