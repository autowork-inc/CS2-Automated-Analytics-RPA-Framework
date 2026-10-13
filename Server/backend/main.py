import os
import time
import hashlib
from pathlib import Path

try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    _env = _root / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from database import (
    init_db,
    license_validate,
    license_create,
    license_list,
    license_revoke,
    license_bind_telegram,
    license_revoke_by_telegram,
    license_get_by_telegram,
    license_reset_device,
    license_save_steamwebapi_key,
    check_parsed,
    check_parsed_batch,
    report_parsed,
    is_license_valid_for_report,
    banned_add,
    banned_remove,
    banned_check,
    get_steamwebapi_key_for_request,
    mark_steamwebapi_key_cooldown,
    update_steamwebapi_key_last_used,
    steamwebapi_pool_add,
    steamwebapi_pool_remove,
    steamwebapi_pool_list,
    steamwebapi_pool_set_active,
    get_user_parsed_stats,
    get_admin_parsed_stats,
    get_api_load_statistics,
)

STEAMWEBAPI_BASE = "https://www.steamwebapi.com/steam/api"
BATCH_CHUNK_SIZE = 20
MAX_STEAM_IDS_PER_REQUEST = 100
MAX_KEY_ATTEMPTS = 5

API_SALT = "example_1_@_key"
CURRENT_CLIENT_VERSION = 1.0

app = FastAPI(title="CS2 API", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def verify_secure_client(request, call_next):
    path = request.url.path
    if path.startswith("/admin") or path.startswith("/download") or path in ["/docs", "/openapi.json", "/redoc", "/api/user/statistics", "/api/version"]:
        return await call_next(request)
    ts = request.headers.get("x-app-timestamp")
    sig = request.headers.get("x-app-signature")
    if not ts or not sig:
        return JSONResponse(status_code=403, content={"detail": "Access Denied: Unofficial Client"})
    try:
        if abs(int(time.time()) - int(ts)) > 60:
            return JSONResponse(status_code=403, content={"detail": "Request Expired"})
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid Timestamp"})
    expected_sig = hashlib.sha256(f"{ts}{API_SALT}".encode()).hexdigest()
    if sig != expected_sig:
        return JSONResponse(status_code=403, content={"detail": "Invalid Signature"})
    return await call_next(request)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/version")
def api_version(request: Request):
    base = str(request.base_url).rstrip("/")
    return {"version": CURRENT_CLIENT_VERSION, "update_url": f"{base}/download/update"}


@app.get("/download/update")
@app.head("/download/update")
def download_update():
    exe_path = Path(__file__).resolve().parent.parent / "release" / "CS2.exe"
    if not exe_path.is_file():
        raise HTTPException(status_code=404, detail="update_not_available")
    return FileResponse(exe_path, filename="CS2.exe", media_type="application/octet-stream")


class ValidateBody(BaseModel):
    key: str
    device_id: str

class ReportParsedBody(BaseModel):
    key: str
    device_id: str
    steam_id: str
    last_value: float | None = None
    name: str | None = None
    country_code: str | None = None

class ReportParsedBatchBody(BaseModel):
    key: str
    device_id: str
    players: list[dict]

class SaveSteamwebapiBody(BaseModel):
    key: str
    device_id: str
    steamwebapi_key: str

class BatchBody(BaseModel):
    key: str
    device_id: str
    steam_ids: list[str]


class SingleInventoryBody(BaseModel):
    key: str
    device_id: str
    steam_id: str


class CheckParsedBatchBody(BaseModel):
    steam_ids: list[str]
    device_id: str | None = None
    key: str | None = None


def _parse_inventory_items(data) -> tuple[float, list]:
    if not isinstance(data, list):
        return 0.0, []
    total = 0.0
    items = []
    for it in data:
        price = it.get("pricelatest") or it.get("pricelatestsell") or 0
        try:
            price = float(price)
        except (ValueError, TypeError):
            price = 0.0
        total += price
        if price > 0:
            items.append({"name": it.get("marketname", "?"), "price": price})
    items.sort(key=lambda x: x["price"], reverse=True)
    return round(total, 2), items[:5]

def _apply_chunk_to_result(result: dict, chunk: list, data) -> None:
    if isinstance(data, dict):
        for sid in chunk:
            raw = data.get(sid)
            if raw is None:
                result[sid] = {"value": None, "items": []}
                continue
            if isinstance(raw, list):
                val, items = _parse_inventory_items(raw)
                result[sid] = {"value": val, "items": items}
            elif isinstance(raw, dict):
                arr = raw.get("items", raw) if isinstance(raw.get("items"), list) else []
                val, items = _parse_inventory_items(arr)
                result[sid] = {"value": val, "items": items}
            else:
                result[sid] = {"value": None, "items": []}
    elif isinstance(data, list):
        for idx, sid in enumerate(chunk):
            if idx < len(data):
                raw = data[idx]
                if isinstance(raw, list):
                    val, items = _parse_inventory_items(raw)
                    result[sid] = {"value": val, "items": items}
                elif isinstance(raw, dict) and isinstance(raw.get("items"), list):
                    val, items = _parse_inventory_items(raw["items"])
                    result[sid] = {"value": val, "items": items}
                else:
                    result[sid] = {"value": None, "items": []}
            else:
                result[sid] = {"value": None, "items": []}
    else:
        for sid in chunk:
            result[sid] = {"value": None, "items": []}

@app.post("/api/inventory/single")
def api_inventory_single(body: SingleInventoryBody):
    if not is_license_valid_for_report(body.key.strip(), body.device_id.strip()):
        raise HTTPException(status_code=403, detail="invalid_license")
    sid = body.steam_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="steam_id required")
    api_key = get_steamwebapi_key_for_request()
    if not api_key:
        raise HTTPException(status_code=503, detail="no_available_api_keys")
    try:
        r = requests.get(
            f"{STEAMWEBAPI_BASE}/inventory/batch",
            params={"key": api_key, "steam_ids": sid, "game": "cs2"},
            headers={"X-API-Key": api_key},
            timeout=20,
        )
    except requests.RequestException as e:
        mark_steamwebapi_key_cooldown(api_key, 30)
        raise HTTPException(status_code=502, detail=str(e))
    if r.status_code == 200:
        update_steamwebapi_key_last_used(api_key)
        try:
            data = r.json()
        except Exception:
            raise HTTPException(status_code=502, detail="steamwebapi_invalid_response")
        result = {}
        _apply_chunk_to_result(result, [sid], data)
        return result
    if r.status_code in (403, 429, 401):
        mark_steamwebapi_key_cooldown(api_key, 60)
    else:
        mark_steamwebapi_key_cooldown(api_key, 30)
    raise HTTPException(status_code=502, detail=f"steamwebapi_{r.status_code}")


@app.post("/api/inventory/batch")
def api_inventory_batch(body: BatchBody):
    if not is_license_valid_for_report(body.key.strip(), body.device_id.strip()):
        raise HTTPException(status_code=403, detail="invalid_license")
    steam_ids = [s.strip() for s in body.steam_ids if s and s.strip()][:MAX_STEAM_IDS_PER_REQUEST]
    if not steam_ids:
        return {}
    result = {}
    for i in range(0, len(steam_ids), BATCH_CHUNK_SIZE):
        chunk = steam_ids[i : i + BATCH_CHUNK_SIZE]
        chunk_done = False
        for attempt in range(MAX_KEY_ATTEMPTS):
            api_key = get_steamwebapi_key_for_request()
            if not api_key:
                raise HTTPException(status_code=503, detail="all_keys_on_cooldown")
            headers = {"X-API-Key": api_key}
            try:
                r = requests.get(
                    f"{STEAMWEBAPI_BASE}/inventory/batch",
                    params={"key": api_key, "steam_ids": ",".join(chunk), "game": "cs2"},
                    headers=headers,
                    timeout=20,
                )
            except requests.RequestException as e:
                print(f"[SteamWebAPI Error] Request failed: {e}")
                mark_steamwebapi_key_cooldown(api_key, 30)
                continue
            
            if r.status_code == 200:
                update_steamwebapi_key_last_used(api_key, count=len(chunk))
                try:
                    data = r.json()
                except Exception:
                    raise HTTPException(status_code=502, detail="steamwebapi_invalid_response")
                _apply_chunk_to_result(result, chunk, data)
                chunk_done = True
                break
            
            print(f"[SteamWebAPI HTTP {r.status_code}] Response: {r.text[:200]}")
            
            if r.status_code in (403, 429, 401):
                mark_steamwebapi_key_cooldown(api_key, 60)
                continue
            mark_steamwebapi_key_cooldown(api_key, 30)
            
        if not chunk_done:
            raise HTTPException(status_code=503, detail="steam_api_failed_or_cooldown")
    return result

@app.post("/validate")
def validate(body: ValidateBody):
    ok, code, expires_at = license_validate(body.key.strip(), body.device_id.strip())
    if not ok:
        raise HTTPException(status_code=403, detail=code)
    return {"status": "ok", "message": code, "expires_at": expires_at}

@app.get("/check_parsed")
def api_check_parsed(steam_id: str):
    if not steam_id or not steam_id.strip():
        raise HTTPException(status_code=400, detail="steam_id required")
    row = check_parsed(steam_id)
    if not row:
        return {"parsed": False}
    out = {"parsed": True, "first_seen": row["first_seen"], "last_seen": row["last_seen"]}
    if row.get("last_value") is not None:
        out["last_value"] = row["last_value"]
    if row.get("name") is not None:
        out["name"] = row["name"]
    return out


@app.post("/check_parsed_batch")
def api_check_parsed_batch(body: CheckParsedBatchBody):
    ids = [s.strip() for s in (body.steam_ids or []) if s and s.strip()]
    data = check_parsed_batch(ids, device_id=body.device_id or None, license_key=body.key or None)
    return data


@app.post("/report_parsed")
def api_report_parsed(body: ReportParsedBody):
    if not is_license_valid_for_report(body.key.strip(), body.device_id.strip()):
        raise HTTPException(status_code=403, detail="invalid_license")
    report_parsed(body.steam_id, body.last_value, body.name, body.country_code, body.device_id.strip(), license_key=body.key.strip() or None)
    return {"status": "ok"}

@app.post("/report_parsed_batch")
def api_report_parsed_batch(body: ReportParsedBatchBody):
    if not is_license_valid_for_report(body.key.strip(), body.device_id.strip()):
        raise HTTPException(status_code=403, detail="invalid_license")
    for p in body.players:
        report_parsed(
            p["steam_id"], 
            p.get("last_value"), 
            p.get("name"), 
            p.get("country_code"), 
            body.device_id.strip(), 
            body.key.strip()
        )
    return {"status": "ok"}

@app.post("/api/save_steamwebapi")
def api_save_steamwebapi(body: SaveSteamwebapiBody):
    if not license_save_steamwebapi_key(body.key.strip(), body.device_id.strip(), body.steamwebapi_key):
        raise HTTPException(status_code=403, detail="invalid_license")
    return {"status": "ok"}

def _check_admin(secret: str, require_full_admin: bool = False):
    from os import environ
    admin_secret = environ.get("PARSER_ADMIN_SECRET", "change_me")
    mod_secret = environ.get("PARSER_MOD_SECRET", "")
    if require_full_admin:
        if secret != admin_secret:
            raise HTTPException(status_code=403, detail="forbidden")
    else:
        if secret != admin_secret and secret != mod_secret:
            raise HTTPException(status_code=403, detail="forbidden")

@app.get("/admin/keys")
def admin_list_keys(admin_secret: str = ""):
    _check_admin(admin_secret)
    return {"keys": license_list()}

@app.post("/admin/keys/create")
def admin_create_key(admin_secret: str = "", days: int = 30):
    _check_admin(admin_secret)
    if not 1 <= days <= 730:
        raise HTTPException(status_code=400, detail="days must be between 1 and 730")
    key = license_create(days=days)
    return {"key": key}

@app.post("/admin/keys/revoke")
def admin_revoke_key(key: str, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not license_revoke(key):
        raise HTTPException(status_code=404, detail="key_not_found")
    return {"status": "revoked"}


@app.post("/admin/keys/reset_device")
def admin_reset_device(key: str, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not license_reset_device(key):
        raise HTTPException(status_code=404, detail="key_not_found")
    return {"status": "reset"}

@app.post("/admin/keys/bind_telegram")
def admin_bind_telegram(key: str, telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not license_bind_telegram(key, telegram_id):
        raise HTTPException(status_code=404, detail="key_not_found")
    return {"status": "ok"}


@app.post("/admin/keys/grant_and_notify")
def admin_grant_and_notify(key: str, telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)

    if not license_bind_telegram(key, telegram_id):
        raise HTTPException(status_code=404, detail="key_not_found")

    cfg = _read_server_env()
    token = cfg.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"status": "ok", "notified": False, "detail": "Нет токена бота в .env"}

    base_dir = os.path.dirname(os.path.abspath(__file__)) 
    root_dir = os.path.dirname(base_dir)  
    release_dir = os.path.join(root_dir, "release")

    release_file = None
    if os.path.isdir(release_dir):
        candidates = []
        for name in os.listdir(release_dir):
            path = os.path.join(release_dir, name)
            if os.path.isfile(path) and any(name.lower().endswith(ext) for ext in [".zip", ".rar", ".exe"]):
                if os.path.getsize(path) <= 49 * 1024 * 1024:
                    candidates.append(path)
        if candidates:
            candidates.sort(
                key=lambda p: 0 if p.lower().endswith(".zip") else (1 if p.lower().endswith(".rar") else 2)
            )
            release_file = candidates[0]

    text = (
        "Ваша подписка активирована.\n\n"
        "Ваш лицензионный ключ:\n"
        f"<code>{key}</code>\n\n"
        "1) Распакуйте архив (если скачиваете впервые).\n"
        "2) Запустите программу и введите этот ключ.\n"
        "3) Один ключ действует на одном ПК."
    )

    try:
        if release_file:
            with open(release_file, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": telegram_id, "caption": text, "parse_mode": "HTML"},
                    files={"document": f},
                    timeout=60,
                )
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        return {"status": "ok", "notified": r.status_code == 200, "sent_file": bool(release_file)}
    except Exception as e:
        return {"status": "ok", "notified": False, "detail": str(e)}

@app.post("/admin/keys/revoke_by_telegram")
def admin_revoke_by_telegram(telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)
    return {"status": "ok", "revoked": license_revoke_by_telegram(telegram_id)}

@app.get("/admin/user")
def admin_user_info(telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)
    return {"telegram_id": telegram_id, "licenses": license_get_by_telegram(telegram_id)}

@app.post("/admin/access/revoke")
def revoke_access(telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)
    banned_add(telegram_id)
    return {"status": "access_revoked"}

@app.post("/admin/access/restore")
def restore_access(telegram_id: int, admin_secret: str = ""):
    _check_admin(admin_secret)
    banned_remove(telegram_id)
    return {"status": "access_restored"}

@app.get("/admin/access/check")
def check_access(telegram_id: int):
    return {"access_denied": banned_check(telegram_id)}

@app.get("/admin/steamwebapi_pool")
def admin_steamwebapi_pool_list(admin_secret: str = ""):
    _check_admin(admin_secret)
    return {"keys": steamwebapi_pool_list()}

@app.post("/admin/steamwebapi_pool/add")
def admin_steamwebapi_pool_add(api_key: str, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=400, detail="api_key required")
    steamwebapi_pool_add(api_key.strip())
    return {"status": "ok"}

@app.post("/admin/steamwebapi_pool/remove")
def admin_steamwebapi_pool_remove(api_key: str, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=400, detail="api_key required")
    steamwebapi_pool_remove(api_key.strip())
    return {"status": "ok"}


@app.post("/admin/steamwebapi_pool/set_active")
def admin_steamwebapi_pool_set_active(api_key: str, active: bool, admin_secret: str = ""):
    _check_admin(admin_secret)
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=400, detail="api_key required")
    steamwebapi_pool_set_active(api_key.strip(), active)
    return {"status": "ok"}


@app.get("/api/user/statistics")
def api_user_statistics(telegram_id: int, days: int = 0, admin_secret: str = ""):
    _check_admin(admin_secret)
    return get_user_parsed_stats(telegram_id, days)


@app.get("/admin/statistics")
def api_admin_statistics(admin_secret: str, period: str = "all"):
    _check_admin(admin_secret)
    if period not in ("day", "all"):
        raise HTTPException(status_code=400, detail="period must be day or all")
    return get_admin_parsed_stats(period)


@app.get("/admin/api_stats")
def admin_api_stats(admin_secret: str = ""):
    _check_admin(admin_secret)
    return get_api_load_statistics()


def _read_server_env() -> dict:
    out = {}
    if not _env.exists():
        return out
    try:
        with open(_env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _write_server_env(data: dict) -> bool:
    if not data:
        return False
    try:
        lines = [f"{k}={v}" for k, v in data.items() if v is not None and str(v).strip() != ""]
        with open(_env, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception:
        return False


CONFIG_UPDATE_ALLOWED_KEYS = {
    "TELEGRAM_BOT_TOKEN", "ADMIN_TELEGRAM_ID", "DOWNLOAD_URL", "PAYMENT_LINK",
    "BACKEND_URL", "STEAMWEBAPI_KEYS",
}


@app.get("/admin/config")
def admin_config_get(admin_secret: str = ""):
    _check_admin(admin_secret, require_full_admin=True)
    cfg = _read_server_env()
    for key in ("PARSER_ADMIN_SECRET", "PARSER_MOD_SECRET"):
        if key in cfg and cfg[key]:
            cfg[key] = "***"
    return cfg


@app.post("/admin/config/update")
async def admin_config_update(request: Request, admin_secret: str = ""):
    _check_admin(admin_secret, require_full_admin=True)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body required")
    current = _read_server_env()
    for k, v in body.items():
        if k in CONFIG_UPDATE_ALLOWED_KEYS and v is not None:
            current[k] = str(v).strip()
    if not _write_server_env(current):
        raise HTTPException(status_code=500, detail="failed to write config")
    return {"status": "ok"}
