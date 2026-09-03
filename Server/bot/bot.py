import csv
import os
import json
import logging
import tempfile
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

BOT_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
ROOT_DIR = os.path.dirname(BOT_DIR)

if os.path.isfile(os.path.join(BOT_DIR, ".env")):
    ROOT_ENV_PATH = os.path.join(BOT_DIR, ".env")
elif os.path.isfile(os.path.join(ROOT_DIR, ".env")):
    ROOT_ENV_PATH = os.path.join(ROOT_DIR, ".env")
else:
    ROOT_ENV_PATH = ".env"

load_dotenv(ROOT_ENV_PATH)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DOWNLOAD_URL = os.getenv("DOWNLOAD_URL", "").strip()

RELEASE_ZIP_PATH = os.getenv("RELEASE_ZIP_PATH", "").strip()
if not RELEASE_ZIP_PATH:
    RELEASE_ZIP_PATH = os.path.join(os.path.dirname(ROOT_ENV_PATH), "release", "cs2_parser_release.zip")
MAX_ZIP_SIZE_MB = 49

SUBSCRIPTION_PRICE = 40 
SUBSCRIPTION_DAYS = 30


def _find_release_file() -> str | None:
    if RELEASE_ZIP_PATH and os.path.isfile(RELEASE_ZIP_PATH):
        try:
            if os.path.getsize(RELEASE_ZIP_PATH) <= MAX_ZIP_SIZE_MB * 1024 * 1024:
                return RELEASE_ZIP_PATH
        except Exception:
            pass

    base_dir = os.path.dirname(ROOT_ENV_PATH)
    release_dir = os.path.join(base_dir, "release")
    if not os.path.isdir(release_dir):
        return None

    exts = [".zip", ".rar", ".exe"]
    candidates = []
    try:
        for name in os.listdir(release_dir):
            path = os.path.join(release_dir, name)
            if not os.path.isfile(path):
                continue
            lower = name.lower()
            if not any(lower.endswith(ext) for ext in exts):
                continue
            try:
                if os.path.getsize(path) <= MAX_ZIP_SIZE_MB * 1024 * 1024:
                    candidates.append(path)
            except Exception:
                continue
    except Exception:
        return None

    if not candidates:
        return None

    def _sort_key(p: str):
        n = os.path.basename(p).lower()
        if n.endswith(".zip"):
            t = 0
        elif n.endswith(".rar"):
            t = 1
        else:
            t = 2
        return (t, n)

    candidates.sort(key=_sort_key)
    return candidates[0]


def get_welcome_text(telegram_id: int) -> str:
    return f"""Привет! 👋"""

SUBSCRIBE_BUTTON_TEXT = "Request License Access"


def _read_root_env() -> dict:
    out = {}
    if not os.path.isfile(ROOT_ENV_PATH):
        return out
    try:
        with open(ROOT_ENV_PATH, "r", encoding="utf-8") as f:
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


def _write_root_env(updates: dict) -> bool:
    try:
        current = _read_root_env()
        current.update(updates)
        lines = [f"{k}={v}" for k, v in current.items() if v is not None and v != ""]
        with open(ROOT_ENV_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        logger.exception("_write_root_env: %s", e)
        return False


def get_backend_url() -> str:
    return (_read_root_env().get("BACKEND_URL") or "url").rstrip("/")


def get_admin_secret() -> str:
    return _read_root_env().get("PARSER_ADMIN_SECRET", "change_me")


def get_payment_link() -> str:
    return (_read_root_env().get("PAYMENT_LINK") or "https://t.me/username").strip()


def get_admin_ids() -> list[int]:
    raw = _read_root_env().get("ADMIN_TELEGRAM_ID", "id")
    ids = []
    for _id in str(raw).split(","):
        try:
            ids.append(int(_id.strip()))
        except ValueError:
            pass
    return ids if ids else [7293801956]


def get_download_url() -> str:
    url = (_read_root_env().get("DOWNLOAD_URL") or "").strip()
    return url or DOWNLOAD_URL or ""


def save_download_url(url: str) -> bool:
    ok = _write_root_env({"DOWNLOAD_URL": (url or "").strip()})
    if ok:
        global DOWNLOAD_URL
        DOWNLOAD_URL = (url or "").strip()
    return ok


def get_user_active_license(telegram_id: int):
    try:
        r = requests.get(
            f"{get_backend_url()}/admin/keys",
            params={"admin_secret": get_admin_secret()},
            timeout=3,
        )
        r.raise_for_status()
        keys = r.json().get("keys", [])
        now = datetime.now(timezone.utc)
        for k in keys:
            if str(k.get("telegram_id")) != str(telegram_id):
                continue
            exp = k.get("expires_at")
            if not exp:
                continue
            try:
                if exp.endswith("Z"):
                    exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                else:
                    exp_dt = datetime.fromisoformat(exp)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt > now:
                    return {"key": (k.get("key") or "").strip(), "expires_at": exp}
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return None


def is_admin(update: Update) -> bool:
    if not update.effective_user:
        return False
    return update.effective_user.id in get_admin_ids()


def is_banned(telegram_id: int) -> bool:
    try:
        r = requests.get(
            f"{get_backend_url()}/admin/access/check",
            params={"telegram_id": telegram_id},
            timeout=2,
        )
        if r.status_code == 200:
            return r.json().get("banned", False)
    except Exception:
        pass
    return False


async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if is_admin(update):
        return False
    if is_banned(user.id):
        if update.message:
            await update.message.reply_text("Вы заблокированы и не можете пользоваться ботом.")
        return True
    return False


def _format_expires_ddmm(expires_at) -> str:
    if not expires_at:
        return ""
    s = (expires_at or "").strip()[:10]
    if len(s) < 10:
        return ""
    try:
        parts = s.split("-")
        if len(parts) == 3:
            return f"{int(parts[2]):02d}.{int(parts[1]):02d}"
    except (ValueError, IndexError):
        pass
    return ""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await check_ban(update, context):
        return
    user = update.effective_user
    telegram_id = user.id if user else 0
    license_info = get_user_active_license(telegram_id)
    if license_info and license_info.get("key"):
        download_url = get_download_url()
        ddmm = _format_expires_ddmm(license_info.get("expires_at"))
        date_line = f"У вас активна подписка до **{ddmm}**!\n\n" if ddmm else "У вас активна подписка!\n\n"
        text = (
            date_line
            + (f"Скачать софт: {download_url}\n\n" if download_url else "")
            + f"Ваш ключ: `{license_info['key']}`\n\n"
            + "Один ключ = один ПК."
        )
        keyboard = [
            [InlineKeyboardButton("📊 Выгрузить статистику", callback_data="user:stats_menu")],
            [InlineKeyboardButton("💬 Поддержка", url=get_payment_link())],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data["home_text"] = text
        context.user_data["home_reply_markup"] = reply_markup
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        return
    text = get_welcome_text(telegram_id)
    keyboard = [[InlineKeyboardButton(SUBSCRIBE_BUTTON_TEXT, url=get_payment_link())]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data["home_text"] = text
    context.user_data["home_reply_markup"] = reply_markup
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


def _parse_days(args: list, default: int = 30) -> int:
    if not args:
        return default
    try:
        n = int(args[0].strip())
        return n if 1 <= n <= 730 else default
    except (ValueError, IndexError):
        return default


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    days = _parse_days(context.args or [], SUBSCRIPTION_DAYS)
    try:
        r = requests.post(
            f"{get_backend_url()}/admin/keys/create",
            params={"admin_secret": get_admin_secret(), "days": days},
            timeout=3,
        )
        r.raise_for_status()
        data = r.json()
        key = data.get("key", "")
        await update.message.reply_text(
            f"Новый ключ (на {days} дн.):\n`{key}`\n\nПередайте пользователю или используйте /grant ID [дней] чтобы отправить ключ и ссылку на софт ему в личку.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("add key")
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /grant TELEGRAM_ID [дней]\nПример: /grant 7293801956 365")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("Укажите числовой Telegram ID пользователя.")
        return
    days = _parse_days((context.args or [])[1:], SUBSCRIPTION_DAYS)
    try:
        r = requests.post(
            f"{get_backend_url()}/admin/keys/create",
            params={"admin_secret": get_admin_secret(), "days": days},
            timeout=3,
        )
        r.raise_for_status()
        key = r.json().get("key", "")
    except Exception as e:
        logger.exception("grant key")
        await update.message.reply_text(f"Ошибка создания ключа: {e}")
        return
    try:
        requests.post(
            f"{get_backend_url()}/admin/keys/bind_telegram",
            params={"key": key, "telegram_id": target_id, "admin_secret": get_admin_secret()},
            timeout=2,
        )
    except Exception:
        pass
    days_text = f"Срок действия — {days} дн."
    release_path = _find_release_file()
    send_file = bool(release_path)
    download_url = get_download_url()
    if send_file:
        msg_lines = [
            "Ваша подписка активирована. Ваш лицензионный ключ:",
            f"`{key}`",
            "",
            "Как пользоваться:",
            "1) Распакуйте полученный архив с программой.",
            "2) Запустите run.bat (или python launcher.py).",
            "3) При первом запуске введите этот ключ в окне активации.",
            "4) Инвентари запрашиваются через сервер (ключ Steamwebapi на сервере).",
            "",
            f"Один ключ действует на одном ПК. {days_text}.",
        ]
    else:
        msg_lines = [
            "Ваша подписка активирована. Ваш лицензионный ключ:",
            f"`{key}`",
            "",
            "Как пользоваться:",
            "1) Скачайте программу ниже или нажмите на ссылку для скачивания.",
            "2) Запустите run.bat (или python launcher.py).",
            "3) При первом запуске введите этот ключ в окне активации.",
            "4) Инвентари запрашиваются через сервер (ключ Steamwebapi на сервере).",
            "",
            f"Один ключ действует на одном ПК. {days_text}.",
        ]
        if download_url:
            msg_lines.append("")
            msg_lines.append("Скачать софт:")
            msg_lines.append(download_url)
        else:
            msg_lines.append("")
            msg_lines.append("Для получения софта укажите ваш ключ в личном сообщении по кнопке ниже.")
    try:
        if send_file and release_path:
            with open(release_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=target_id,
                    document=f,
                    filename=os.path.basename(release_path),
                    caption="Архив с программой CS2 Inventory Parser.",
                )
        reply_markup = None
        if not send_file and not download_url:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Получить софт в ЛС", url=get_payment_link())]])
        await context.bot.send_message(
            chat_id=target_id,
            text="\n".join(msg_lines),
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        await update.message.reply_text(
            f"Ключ и инструкция отправлены пользователю (ID {target_id})."
            + (" Файл с программой отправлен пользователю." if send_file else "")
        )
    except Exception as e:
        await update.message.reply_text(
            f"Не удалось отправить сообщение пользователю {target_id}. "
            "Пусть он сначала напишет боту /start. Ошибка: " + str(e)
        )
        await update.message.reply_text(f"Ключ для выдачи вручную: `{key}`", parse_mode="Markdown")


async def cmd_list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    try:
        r = requests.get(
            f"{get_backend_url()}/admin/keys",
            params={"admin_secret": get_admin_secret()},
            timeout=3,
        )
        r.raise_for_status()
        data = r.json()
        keys = data.get("keys", [])
        if not keys:
            await update.message.reply_text("Нет ключей.")
            return
        lines = []
        for k in keys[:30]:
            full_key = (k.get("key") or "").strip()
            bound = "привязан" if k.get("device_id") else "не привязан"
            exp = (k.get("expires_at") or "")[:10] or "—"
            tid = k.get("telegram_id") or "—"
            lines.append(f"`{full_key}` — {bound}, до {exp}, TG: {tid}")
        await update.message.reply_text("\n".join(lines) or "Нет ключей.", parse_mode="Markdown")
    except Exception as e:
        logger.exception("list keys")
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    key = " ".join(context.args).strip() if context.args else ""
    if not key:
        await update.message.reply_text("Использование: /revoke KEY")
        return
    try:
        r = requests.post(
            f"{get_backend_url()}/admin/keys/revoke",
            params={"key": key, "admin_secret": get_admin_secret()},
            timeout=3,
        )
        if r.status_code == 404:
            await update.message.reply_text("Ключ не найден.")
            return
        r.raise_for_status()
        await update.message.reply_text("Ключ отозван.")
    except Exception as e:
        logger.exception("revoke")
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_revoke_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /revoke_user TELEGRAM_ID")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("Укажите числовой Telegram ID.")
        return
    try:
        r = requests.post(
            f"{get_backend_url()}/admin/keys/revoke_by_telegram",
            params={"telegram_id": target_id, "admin_secret": get_admin_secret()},
            timeout=3,
        )
        r.raise_for_status()
        n = r.json().get("revoked", 0)
        await update.message.reply_text(f"Подписка отозвана. Отозвано ключей: {n}.")
    except Exception as e:
        logger.exception("revoke_user")
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /user TELEGRAM_ID")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("Укажите числовой Telegram ID.")
        return
    try:
        r = requests.get(
            f"{get_backend_url()}/admin/user",
            params={"telegram_id": target_id, "admin_secret": get_admin_secret()},
            timeout=3,
        )
        r.raise_for_status()
        data = r.json()
        licenses = data.get("licenses", [])
        if not licenses:
            await update.message.reply_text(f"Пользователь {target_id}: ключей нет.")
            return
        lines = [f"Пользователь {target_id}:"]
        for lic in licenses:
            exp = (lic.get("expires_at") or "")[:10] or "—"
            has_api = "да" if (lic.get("steamwebapi_key") or "").strip() else "нет"
            lines.append(f"• Ключ …{lic.get('key', '')[-8:]}, до {exp}, Steamwebapi: {has_api}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.exception("user")
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban TELEGRAM_ID")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("Укажите числовой Telegram ID.")
        return
    try:
        requests.post(
            f"{get_backend_url()}/admin/access/revoke",
            params={"telegram_id": target_id, "admin_secret": get_admin_secret()},
            timeout=3,
        )
        await update.message.reply_text(f"Пользователь {target_id} заблокирован в боте.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban TELEGRAM_ID")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("Укажите числовой Telegram ID.")
        return
    try:
        requests.post(
            f"{get_backend_url()}/admin/access/restore",
            params={"telegram_id": target_id, "admin_secret": get_admin_secret()},
            timeout=3,
        )
        await update.message.reply_text(f"Пользователь {target_id} разблокирован.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await check_ban(update, context):
        return
    if not is_admin(update):
        await update.message.reply_text("Доступ запрещён.")
        return
    keyboard = _admin_main_keyboard()
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Админ-панель\nВыберите действие:", reply_markup=reply_markup)


def _admin_main_keyboard():
    return [
        [InlineKeyboardButton("🔑 Работа с лицензиями", callback_data="admin:licenses")],
        [InlineKeyboardButton("👤 Работа с пользователями", callback_data="admin:users")],
        [InlineKeyboardButton("🔗 Указать ссылку на софт", callback_data="admin:set_download_url")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton("❓ Помощь с командами", callback_data="admin:help")],
    ]


def _admin_licenses_keyboard():
    return [
        [InlineKeyboardButton("Создать ключ", callback_data="admin:add")],
        [InlineKeyboardButton("Выдать ключ", callback_data="admin:grant_help")],
        [InlineKeyboardButton("Отозвать ключ", callback_data="admin:revoke_prompt")],
        [InlineKeyboardButton("Список ключей", callback_data="admin:list")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="admin:main")],
    ]


def _admin_users_keyboard():
    return [
        [InlineKeyboardButton("Инфо о пользователе", callback_data="admin:user_help")],
        [InlineKeyboardButton("Забрать / Выдать", callback_data="admin:ban_help")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="admin:main")],
    ]


async def _send_admin_stats_file(query, context, period: str, back_markup):
    try:
        r = requests.get(
            f"{get_backend_url()}/admin/statistics",
            params={"admin_secret": get_admin_secret(), "period": period},
            timeout=20,
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            await query.edit_message_text("Нет данных за выбранный период.", reply_markup=back_markup)
            return
    except Exception as e:
        logger.exception("admin statistics")
        await query.edit_message_text(f"Ошибка: {e}", reply_markup=back_markup)
        return
    fd, path = tempfile.mkstemp(prefix="admin_stats_", suffix=".csv")
    os.close(fd)
    try:
        header = ["Ссылка Steam", "Никнейм", "Инвентарь ($)", "Дата проверки", "Telegram ID", "Ключ"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            w.writerow(header)
            for row in rows:
                sid = str(row.get("steam_id") or "").strip()
                link = f"https://steamcommunity.com/profiles/{sid}" if sid else ""
                name = str(row.get("name") or "").strip()
                val = row.get("last_value")
                try:
                    val_str = f"{float(val):.2f}" if val is not None else ""
                except (ValueError, TypeError):
                    val_str = ""
                dt = (row.get("last_seen") or "")[:10]
                tg_id = row.get("telegram_id") or ""
                lic_key = (row.get("license_key") or "").strip()
                w.writerow([link, name, val_str, dt, tg_id, lic_key])
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename=f"admin_statistics_{period}.csv",
                caption=f"Статистика: {period}.",
            )
        await query.edit_message_text("Файл отправлен.", reply_markup=back_markup)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def callback_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        await query.edit_message_text("Доступ запрещён.")
        return
    data = (query.data or "").strip()
    back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data="admin:main")]])

    if data == "admin:main":
        await query.edit_message_text("Админ-панель\nВыберите действие:", reply_markup=InlineKeyboardMarkup(_admin_main_keyboard()))
        return
    if data == "admin:licenses":
        await query.edit_message_text("Работа с лицензиями:", reply_markup=InlineKeyboardMarkup(_admin_licenses_keyboard()))
        return
    if data == "admin:users":
        await query.edit_message_text("Работа с пользователями:", reply_markup=InlineKeyboardMarkup(_admin_users_keyboard()))
        return
    if data == "admin:stats":
        kb = [
            [InlineKeyboardButton("За день", callback_data="admin:stats_day")],
            [InlineKeyboardButton("За всё время", callback_data="admin:stats_all")],
            [InlineKeyboardButton("Пользователя", callback_data="admin:stats_user_prompt")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="admin:main")],
        ]
        await query.edit_message_text("Статистика:", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "admin:add":
        try:
            r = requests.post(
                f"{get_backend_url()}/admin/keys/create",
                params={"admin_secret": get_admin_secret()},
                timeout=3,
            )
            r.raise_for_status()
            key = r.json().get("key", "")
            await query.edit_message_text(
                f"Новый ключ (30 дней):\n`{key}`\n\nИспользуй кнопку «Выдать ключ» или /grant ID чтобы отправить пользователю.",
                parse_mode="Markdown",
                reply_markup=back_markup,
            )
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {e}", reply_markup=back_markup)
        return
    if data == "admin:list":
        try:
            r = requests.get(
                f"{get_backend_url()}/admin/keys",
                params={"admin_secret": get_admin_secret()},
                timeout=3,
            )
            r.raise_for_status()
            keys = r.json().get("keys", [])
            if not keys:
                await query.edit_message_text("Нет ключей.", reply_markup=back_markup)
                return
            lines = []
            for k in keys[:25]:
                full_key = (k.get("key") or "").strip()
                bound = "привязан" if k.get("device_id") else "не привязан"
                exp = (k.get("expires_at") or "")[:10] or "—"
                tid = k.get("telegram_id") or "—"
                lines.append(f"`{full_key}` — {bound}, до {exp}, TG: {tid}")
            await query.edit_message_text("\n".join(lines) or "Нет ключей.", parse_mode="Markdown", reply_markup=back_markup)
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {e}", reply_markup=back_markup)
        return
    if data == "admin:help":
        text = """Команды (вводи в чат):
/grant ID — выдать ключ и софт пользователю
/revoke KEY — отозвать ключ
/revoke_user ID — отобрать подписку
/user ID — инфо о пользователе
/revoke_access ID
/restore_access ID"""
        await query.edit_message_text(text, reply_markup=back_markup)
        return
    if data == "admin:grant_help":
        await query.edit_message_text("Отправь в чат: /grant TELEGRAM_ID\nПример: /grant 123456789", reply_markup=back_markup)
        return
    if data == "admin:revoke_help":
        await query.edit_message_text("Отозвать ключ: /revoke KEY\nОтобрать подписку у пользователя: /revoke_user TELEGRAM_ID", reply_markup=back_markup)
        return
    if data == "admin:user_help":
        await query.edit_message_text("Отправь: /user TELEGRAM_ID", reply_markup=back_markup)
        return
    if data == "admin:ban_help":
        await query.edit_message_text("Забанить: /ban TELEGRAM_ID\nРазбанить: /unban TELEGRAM_ID", reply_markup=back_markup)
        return
    if data == "admin:set_download_url":
        kb = [
            [InlineKeyboardButton("Брать из Release", callback_data="admin:download_from_release")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="admin:main")],
        ]
        await query.edit_message_text(
            "Пришлите URL ссылки на софт (одним сообщением) или нажмите «Брать из Release» (ссылка будет сброшена). Текущая: " + (get_download_url() or "не задана"),
            reply_markup=InlineKeyboardMarkup(kb),
        )
        context.user_data["awaiting_download_url"] = True
        return
    if data == "admin:download_from_release":
        context.user_data.pop("awaiting_download_url", None)
        save_download_url("")
        await query.edit_message_text(
            "Ссылка сброшена. При выдаче ключа без архива пользователю будет показана кнопка для связи.",
            reply_markup=back_markup,
        )
        return
    if data == "admin:revoke_prompt":
        context.user_data["awaiting_revoke_key"] = True
        await query.edit_message_text("Пришлите ключ текстом (полностью, для отзыва). Скопируйте из списка ключей.", reply_markup=back_markup)
        return

    if data == "admin:stats_day":
        await _send_admin_stats_file(query, context, period="day", back_markup=back_markup)
        return
    if data == "admin:stats_all":
        await _send_admin_stats_file(query, context, period="all", back_markup=back_markup)
        return
    if data == "admin:stats_user_prompt":
        context.user_data["awaiting_admin_stats_user"] = True
        await query.edit_message_text("Отправьте Telegram ID пользователя (числом).", reply_markup=back_markup)
        return


async def cmd_help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await check_ban(update, context):
        return
    if not is_admin(update):
        await update.message.reply_text("Используйте /start для информации о подписке и софте.")
        return
    text = "Админ-команды: /admin — открыть админ-панель с кнопками.\nОстальное: /add, /grant ID, /list_keys, /revoke KEY, /revoke_user ID, /user ID, /revoke_access ID, /restore_access ID"
    await update.message.reply_text(text)


async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and await check_ban(update, context):
        return
    if is_admin(update) and context.user_data.pop("awaiting_download_url", False):
        url = (update.message.text or "").strip()
        if not url:
            await update.message.reply_text("URL пустой. Отправьте ссылку одним сообщением.")
            return
        if save_download_url(url):
            await update.message.reply_text(f"Ссылка на софт сохранена в .env:\n{url}")
        else:
            await update.message.reply_text("Не удалось сохранить (проверьте файл .env в корне проекта).")
        return
    if is_admin(update) and context.user_data.pop("awaiting_admin_stats_user", False):
        text = (update.message.text or "").strip()
        try:
            target_id = int(text)
        except ValueError:
            await update.message.reply_text("Укажите числовой Telegram ID.")
            return
        try:
            r = requests.get(
                f"{get_backend_url()}/api/user/statistics",
                params={"telegram_id": target_id, "days": 0, "admin_secret": get_admin_secret()},
                timeout=20,
            )
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                await update.message.reply_text(f"Нет данных по пользователю {target_id}.")
                return
        except Exception as e:
            logger.exception("admin stats user")
            await update.message.reply_text(f"Ошибка: {e}")
            return
        fd, path = tempfile.mkstemp(prefix="user_stats_", suffix=".csv")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
                w.writerow(["Ссылка Steam", "Никнейм", "Инвентарь ($)", "Дата проверки"])
                for row in rows:
                    sid = str(row.get("steam_id") or "").strip()
                    link = f"https://steamcommunity.com/profiles/{sid}" if sid else ""
                    name = str(row.get("name") or "").strip()
                    val = row.get("last_value")
                    try:
                        val_str = f"{float(val):.2f}" if val is not None else ""
                    except (ValueError, TypeError):
                        val_str = ""
                    dt = (row.get("last_seen") or "")[:10]
                    w.writerow([link, name, val_str, dt])
            with open(path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_user.id,
                    document=f,
                    filename=f"user_{target_id}_statistics.csv",
                    caption=f"Статистика пользователя {target_id} (всё время).",
                )
            await update.message.reply_text("Файл отправлен.")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return
    if is_admin(update) and context.user_data.pop("awaiting_revoke_key", False):
        key = (update.message.text or "").strip()
        if not key:
            await update.message.reply_text("Ключ пустой. Отправьте ключ целиком.")
            return
        try:
            r = requests.post(
                f"{get_backend_url()}/admin/keys/revoke",
                params={"key": key, "admin_secret": get_admin_secret()},
                timeout=3,
            )
            if r.status_code == 404:
                await update.message.reply_text("Ключ не найден.")
                return
            r.raise_for_status()
            await update.message.reply_text("Ключ отозван.")
        except Exception as e:
            logger.exception("revoke key from prompt")
            await update.message.reply_text(f"Ошибка: {e}")
        return
    pass


async def callback_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not user:
        return
    data = (query.data or "").strip()
    if data == "user:stats_menu":
        kb = [
            [
                InlineKeyboardButton("За сегодня", callback_data="user:stats_1"),
                InlineKeyboardButton("За неделю", callback_data="user:stats_7"),
            ],
            [
                InlineKeyboardButton("За всё время", callback_data="user:stats_0"),
            ],
            [
                InlineKeyboardButton("⬅ Назад", callback_data="user:stats_back"),
            ],
        ]
        await query.edit_message_text(
            "Выберите период для выгрузки статистики:",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return
    if data == "user:stats_back":
        home_text = context.user_data.get("home_text")
        home_markup = context.user_data.get("home_reply_markup")
        if home_text and home_markup:
            await query.edit_message_text(
                home_text,
                parse_mode="Markdown",
                reply_markup=home_markup,
            )
        else:
            fake_update = Update(update.update_id, message=query.message)
            await start(fake_update, context)
        return
    if data.startswith("user:stats_"):
        days_str = data.split("_", 1)[-1]
        try:
            days = int(days_str)
        except ValueError:
            days = 0
        try:
            r = requests.get(
                f"{get_backend_url()}/api/user/statistics",
                params={
                    "telegram_id": user.id,
                    "days": days,
                    "admin_secret": get_admin_secret(),
                },
                timeout=20,
            )
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                kb = [
                    [
                        InlineKeyboardButton("За сегодня", callback_data="user:stats_1"),
                        InlineKeyboardButton("За неделю", callback_data="user:stats_7"),
                    ],
                    [
                        InlineKeyboardButton("За всё время", callback_data="user:stats_0"),
                    ],
                    [
                        InlineKeyboardButton("⬅ Назад", callback_data="user:stats_back"),
                    ],
                ]
                try:
                    await query.edit_message_text("Нет данных за этот период.", reply_markup=InlineKeyboardMarkup(kb))
                except BadRequest as e:
                    if "Message is not modified" in str(e):
                        pass
                    else:
                        raise
                return
        except Exception as e:
            logger.exception("user statistics")
            await query.edit_message_text(f"Ошибка запроса статистики: {e}")
            return

        fd, path = tempfile.mkstemp(prefix="statistics_", suffix=".csv")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
                w.writerow(["Ссылка Steam", "Никнейм", "Инвентарь ($)", "Дата проверки"])
                for row in rows:
                    sid = str(row.get("steam_id") or "").strip()
                    link = f"https://steamcommunity.com/profiles/{sid}" if sid else ""
                    name = str(row.get("name") or "").strip()
                    val = row.get("last_value")
                    try:
                        val_str = f"{float(val):.2f}" if val is not None else ""
                    except (ValueError, TypeError):
                        val_str = ""
                    dt = (row.get("last_seen") or "")[:10]
                    w.writerow([link, name, val_str, dt])

            with open(path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user.id,
                    document=f,
                    filename="statistics.csv",
                    caption="Статистика проверенных игроков (от 150$).",
                )
            await query.edit_message_text("Файл statistics.csv отправлен.")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_admin, pattern="^admin:"))
    app.add_handler(CallbackQueryHandler(callback_user, pattern="^user:"))
    app.add_handler(CommandHandler("help", cmd_help_admin))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("list_keys", cmd_list_keys))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("revoke_user", cmd_revoke_user))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("revoke_access", cmd_ban))
    app.add_handler(CommandHandler("restore_access", cmd_unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
