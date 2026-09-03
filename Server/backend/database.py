import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.environ.get("PARSER_DB_PATH", os.path.join(os.path.dirname(__file__), "parser.db"))


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS licenses (
                key TEXT PRIMARY KEY,
                device_id TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS shared_parsed (
                steam_id TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_value REAL,
                name TEXT,
                country_code TEXT,
                device_id TEXT,
                UNIQUE(steam_id)
            );
            CREATE INDEX IF NOT EXISTS idx_shared_steam ON shared_parsed(steam_id);
            CREATE TABLE IF NOT EXISTS steamwebapi_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT UNIQUE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_used_at TEXT,
                created_at TEXT NOT NULL
            );
        """)
        try:
            conn.execute("SELECT expires_at FROM licenses LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE licenses ADD COLUMN expires_at TEXT")
            conn.execute("UPDATE licenses SET expires_at = datetime(created_at, '+30 days') WHERE expires_at IS NULL")
        for col in ("telegram_id", "steamwebapi_key"):
            try:
                conn.execute(f"SELECT {col} FROM licenses LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE licenses ADD COLUMN {col} TEXT")
        try:
            conn.execute("SELECT license_key FROM shared_parsed LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE shared_parsed ADD COLUMN license_key TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                telegram_id TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT,
                timestamp TEXT
            )
        """)

        for col, col_type in (
            ("cooldown_until", "TEXT"),
            ("usage_month", "TEXT"),
            ("usage_count", "INTEGER"),
        ):
            try:
                conn.execute(f"SELECT {col} FROM steamwebapi_keys LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE steamwebapi_keys ADD COLUMN {col} {col_type}")
        conn.execute("UPDATE steamwebapi_keys SET usage_count = 0 WHERE usage_count IS NULL")

        env_keys = (os.environ.get("STEAMWEBAPI_KEYS") or "").strip()
        if env_keys:
            existing = conn.execute("SELECT COUNT(*) AS c FROM steamwebapi_keys").fetchone()
            if existing and existing["c"] == 0:
                now_iso = datetime.utcnow().isoformat()
                for raw in env_keys.split(","):
                    k = raw.strip()
                    if not k:
                        continue
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO steamwebapi_keys (api_key, is_active, created_at) VALUES (?, 1, ?)",
                            (k, now_iso),
                        )
                    except Exception:
                        pass


def license_validate(key: str, device_id: str) -> tuple[bool, str, str]:
    now_iso = datetime.utcnow().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT device_id, expires_at FROM licenses WHERE key = ?",
            (key.strip(),)
        ).fetchone()
        if not row:
            return False, "invalid_key", ""
        expires_at = row["expires_at"] if row["expires_at"] else ""
        if expires_at and expires_at < now_iso:
            return False, "expired", ""
        bound = row["device_id"]
        if bound is None:
            conn.execute(
                "UPDATE licenses SET device_id = ? WHERE key = ?",
                (device_id, key.strip())
            )
            return True, "activated", expires_at
        if bound != device_id:
            return False, "already_used", ""
        return True, "ok", expires_at


def license_create(days: int = 30) -> str:
    import uuid
    from datetime import timedelta
    key = str(uuid.uuid4()).replace("-", "")[:24].upper()
    now = datetime.utcnow()
    expires = (now + timedelta(days=days)).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO licenses (key, device_id, created_at, expires_at) VALUES (?, NULL, ?, ?)",
            (key, now.isoformat(), expires)
        )
    return key


def license_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key, device_id, created_at, expires_at, telegram_id, steamwebapi_key FROM licenses ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def license_bind_telegram(key: str, telegram_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE licenses SET telegram_id = ? WHERE key = ?",
            (str(telegram_id), key.strip())
        )
    return cur.rowcount > 0


def license_revoke_by_telegram(telegram_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM licenses WHERE telegram_id = ?", (str(telegram_id),))
        n = cur.rowcount
    return n


def license_get_by_telegram(telegram_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key, device_id, created_at, expires_at, steamwebapi_key FROM licenses WHERE telegram_id = ?",
            (str(telegram_id),)
        ).fetchall()
    return [dict(r) for r in rows]


def license_reset_device(key: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE licenses SET device_id = NULL WHERE key = ?",
            (key.strip(),),
        )
    return cur.rowcount > 0


def license_save_steamwebapi_key(key: str, device_id: str, steamwebapi_key: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM licenses WHERE key = ? AND device_id = ?",
            (key.strip(), device_id.strip())
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE licenses SET steamwebapi_key = ? WHERE key = ?",
            (steamwebapi_key.strip(), key.strip())
        )
    return True


def steamwebapi_pool_add(api_key: str) -> None:
    if not api_key or not api_key.strip():
        return
    api_key = api_key.strip()
    now_iso = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO steamwebapi_keys (api_key, is_active, created_at) VALUES (?, 1, ?)",
            (api_key, now_iso),
        )


def steamwebapi_pool_remove(api_key: str) -> None:
    if not api_key or not api_key.strip():
        return
    api_key = api_key.strip()
    with get_db() as conn:
        conn.execute(
            "DELETE FROM steamwebapi_keys WHERE api_key = ?",
            (api_key,),
        )


def steamwebapi_pool_set_active(api_key: str, is_active: bool) -> None:
    if not api_key or not api_key.strip():
        return
    api_key = api_key.strip()
    with get_db() as conn:
        conn.execute(
            "UPDATE steamwebapi_keys SET is_active = ? WHERE api_key = ?",
            (1 if is_active else 0, api_key),
        )


def steamwebapi_pool_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, api_key, is_active, last_used_at, created_at, cooldown_until, usage_month, usage_count FROM steamwebapi_keys ORDER BY id"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        key = d.get("api_key", "")
        if len(key) > 8:
            d["api_key_masked"] = key[:4] + "..." + key[-4:]
        else:
            d["api_key_masked"] = "***"
        d["usage_month"] = d.get("usage_month")
        d["usage_count"] = d.get("usage_count") or 0
        out.append(d)
    return out


def get_steamwebapi_key_for_request() -> str | None:
    now_iso = datetime.utcnow().isoformat()
    with get_db() as conn:
        row = conn.execute(
            (now_iso,),
        ).fetchone()
    return row["api_key"] if row else None


def mark_steamwebapi_key_cooldown(api_key: str, seconds: int = 60) -> None:
    from datetime import timedelta
    now = datetime.utcnow()
    until = (now + timedelta(seconds=seconds)).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE steamwebapi_keys SET cooldown_until = ? WHERE api_key = ?",
            (until, api_key.strip()),
        )


def update_steamwebapi_key_last_used(api_key: str, count: int = 1) -> None:
    now = datetime.utcnow()
    now_iso = now.isoformat()
    month_str = now.strftime("%Y-%m")
    with get_db() as conn:
        row = conn.execute(
            "SELECT usage_month, usage_count FROM steamwebapi_keys WHERE api_key = ?",
            (api_key.strip(),),
        ).fetchone()
        
        if row and row["usage_month"] == month_str:
            new_count = (row["usage_count"] or 0) + count
            conn.execute(
                "UPDATE steamwebapi_keys SET last_used_at = ?, cooldown_until = NULL, usage_month = ?, usage_count = ? WHERE api_key = ?",
                (now_iso, month_str, new_count, api_key.strip()),
            )
        else:
            conn.execute(
                "UPDATE steamwebapi_keys SET last_used_at = ?, cooldown_until = NULL, usage_month = ?, usage_count = ? WHERE api_key = ?",
                (now_iso, month_str, count, api_key.strip()),
            )
            
        logs = [(api_key.strip(), now_iso)] * count
        conn.executemany(
            "INSERT INTO api_usage_logs (api_key, timestamp) VALUES (?, ?)",
            logs,
        )


def get_api_load_statistics() -> dict:
    from datetime import timedelta
    now = datetime.utcnow()
    since = (now - timedelta(hours=24)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp FROM api_usage_logs WHERE timestamp >= ?",
            (since,),
        ).fetchall()
    by_hour: dict[str, int] = {}
    for row in rows:
        ts = row[0]
        if not ts:
            continue
        try:
            if "T" in ts:
                part = ts.split("T")[0]
                t_part = ts.split("T")[1][:2]  # HH
            else:
                part = ts.split(" ")[0]
                t_part = ts.split(" ")[1][:2] if " " in ts else "00"
            key = f"{part} {t_part}:00"
            by_hour[key] = by_hour.get(key, 0) + 1
        except Exception:
            continue
    total = sum(by_hour.values())
    peak_hour = None
    peak_count = 0
    for h, c in by_hour.items():
        if c > peak_count:
            peak_count = c
            peak_hour = h
    return {
        "total_requests": total,
        "by_hour": by_hour,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
    }


def banned_add(telegram_id: int) -> None:
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO banned_users (telegram_id) VALUES (?)", (str(telegram_id),))


def banned_remove(telegram_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM banned_users WHERE telegram_id = ?", (str(telegram_id),))
    return cur.rowcount > 0


def banned_check(telegram_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM banned_users WHERE telegram_id = ?", (str(telegram_id),)).fetchone()
    return row is not None


def license_revoke(key: str) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM licenses WHERE key = ?", (key.strip(),))
        n = cur.rowcount
    return n > 0


def check_parsed(steam_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT steam_id, first_seen, last_seen, last_value, name, country_code FROM shared_parsed WHERE steam_id = ?",
            (steam_id.strip(),)
        ).fetchone()
    if not row:
        return None
    return dict(row)


def check_parsed_batch(steam_ids: list[str], device_id: str | None = None, license_key: str | None = None) -> dict:
    if not steam_ids:
        return {}
    ids = [s.strip() for s in steam_ids if s and s.strip()]
    if not ids:
        return {}
    out = {}
    with get_db() as conn:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            "SELECT steam_id, first_seen, last_seen, last_value, name, device_id, license_key FROM shared_parsed WHERE steam_id IN (" + placeholders + ")",
            ids,
        ).fetchall()
        my_telegram = None
        if (device_id or "").strip() and (license_key or "").strip():
            row_me = conn.execute(
                "SELECT telegram_id FROM licenses WHERE key = ? AND device_id = ?",
                (license_key.strip(), device_id.strip()),
            ).fetchone()
            if row_me and row_me["telegram_id"]:
                my_telegram = row_me["telegram_id"]
        for row in rows:
            r = dict(row)
            sid = r["steam_id"]
            parsed_by_you = False
            if device_id or license_key:
                rec_did = (r.get("device_id") or "").strip()
                rec_key = (r.get("license_key") or "").strip()
                if (device_id or "").strip() and rec_did and rec_did == (device_id or "").strip():
                    parsed_by_you = True
                elif (license_key or "").strip() and rec_key and rec_key == (license_key or "").strip():
                    parsed_by_you = True
                elif my_telegram and rec_did:
                    row_rec = conn.execute(
                        "SELECT telegram_id FROM licenses WHERE device_id = ?",
                        (rec_did,),
                    ).fetchone()
                    if row_rec and row_rec["telegram_id"] and row_rec["telegram_id"] == my_telegram:
                        parsed_by_you = True
            out[sid] = {
                "parsed": True,
                "last_seen": r.get("last_seen"),
                "last_value": r.get("last_value"),
                "name": r.get("name"),
                "parsed_by_you": parsed_by_you,
            }
    return out


def report_parsed(steam_id: str, last_value: float | None, name: str | None, country_code: str | None, device_id: str | None, license_key: str | None = None) -> None:
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            (steam_id.strip(), now, now, last_value, name or "", country_code or "", device_id or "", (license_key or "").strip() or None)
        )


def is_license_valid_for_report(key: str, device_id: str) -> bool:
    now_iso = datetime.utcnow().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT device_id, expires_at FROM licenses WHERE key = ?",
            (key.strip(),)
        ).fetchone()
        if not row or row["device_id"] is None:
            return False
        if row["expires_at"] and row["expires_at"] < now_iso:
            return False
        return row["device_id"] == device_id


def get_user_parsed_stats(telegram_id: int, days: int, min_value: float = 150.0) -> list[dict]:
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        days_int = 0
    params = [str(telegram_id)]
    where = "device_id IN (SELECT device_id FROM licenses WHERE telegram_id = ?) AND last_value IS NOT NULL AND last_value >= ?"
    params.append(float(min_value))
    if days_int == 1:
        where += " AND date(last_seen) = date('now', 'localtime')"
    elif days_int > 1:
        where += " AND last_seen >= datetime('now', 'localtime', ?)"
        params.append(f"-{days_int} days")
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT steam_id, name, last_value, last_seen FROM shared_parsed WHERE {where} ORDER BY last_value DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_admin_parsed_stats(period: str, min_value: float = 150.0) -> list[dict]:
    where = "sp.last_value IS NOT NULL AND sp.last_value >= ?"
    params = [float(min_value)]
    if period == "day":
        where += " AND date(last_seen) = date('now', 'localtime')"
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                sp.steam_id,
                sp.name,
                sp.last_value,
                sp.last_seen,
                l.telegram_id AS telegram_id,
                l.key AS license_key
            FROM shared_parsed sp
            LEFT JOIN licenses l ON sp.device_id = l.device_id
            WHERE {where}
            ORDER BY sp.last_seen DESC
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]
