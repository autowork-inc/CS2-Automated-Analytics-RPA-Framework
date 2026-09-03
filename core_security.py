import hashlib
import subprocess
import os
import time
import json
import requests

API_SALT = "example_1_@_key"


def get_device_id() -> str:
    
    hwid_parts: list = []

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            if isinstance(machine_guid, str) and machine_guid.strip():
                hwid_parts.append(machine_guid.strip())
    except Exception:
        pass

    try:
        output = subprocess.check_output("wmic csproduct get uuid", shell=True, stderr=subprocess.DEVNULL).decode(errors="ignore")
        lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        if len(lines) >= 2:
            mb_uuid = lines[1].strip()
            if mb_uuid and mb_uuid not in {"FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "00000000-0000-0000-0000-000000000000"}:
                hwid_parts.append(mb_uuid)
    except Exception:
        pass

    if not hwid_parts:
        fallback_file = "fallback_hwid.json"
        try:
            if os.path.exists(fallback_file):
                with open(fallback_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                    hwid = (data.get("hwid") or "").strip()
                    if hwid:
                        return hwid
        except Exception:
            pass
        import uuid
        new_hwid = hashlib.sha256(str(uuid.uuid4()).encode("utf-8")).hexdigest()
        try:
            with open(fallback_file, "w", encoding="utf-8") as f:
                json.dump({"hwid": new_hwid}, f)
        except Exception:
            pass
        return new_hwid

    unique_string = "-".join(hwid_parts)
    return hashlib.sha256(unique_string.encode("utf-8")).hexdigest()


def secure_api_call(url: str, method: str = "GET", json_data=None, params=None, timeout: int = 15):
    
    ts = str(int(time.time()))
    signature = hashlib.sha256(f"{ts}{API_SALT}".encode()).hexdigest()
    headers = {
        "X-App-Timestamp": ts,
        "X-App-Signature": signature,
    }
    if method.upper() == "POST":
        return requests.post(url, json=json_data, params=params, headers=headers, timeout=timeout)
    return requests.get(url, params=params, headers=headers, timeout=timeout)


if __name__ == "__main__":
    print("Твой железобетонный HWID:", get_device_id())
