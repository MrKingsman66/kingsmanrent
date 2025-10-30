import asyncio
import uuid
import re
import html
import os
import json
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

# 🔧 Настройки из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = -1002773883024
TOPIC_ORDERS = 81003
TOPIC_SUPPORT = 81451
ADMIN_IDS = [841285005]

# Сотрудники будут загружаться из Google Sheets
STAFF_MEMBERS = {}

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен в переменных окружения")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Настройки Google Sheets ---
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SPREADSHEET_NAME = 'Kingsman Rent Orders'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# Глобальные переменные
creds = None
gc = None
worksheet_orders = None
worksheet_assignments = None
worksheet_staff = None
sheets_enabled = False

# Временные данные (только для текущей сессии)
player_data = {}
support_requests = []
order_confirmations = {}
staff_management_data = {}


def init_google_sheets():
    """Инициализация Google Sheets из переменной окружения"""
    global creds, gc, worksheet_orders, worksheet_assignments, worksheet_staff, sheets_enabled
    
    try:
        # Проверяем наличие переменной
        if not SERVICE_ACCOUNT_JSON:
            print("❌ SERVICE_ACCOUNT_JSON не установлен в переменных окружения")
            return False
        
        # Пытаемся распарсить JSON
        try:
            service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            print(f"📝 Полученная строка: {SERVICE_ACCOUNT_JSON[:100]}...")  # Первые 100 символов для отладки
            return False
        
        # Создаем временный файл
        temp_file = "temp_service_account.json"
        with open(temp_file, 'w') as f:
            json.dump(service_account_info, f)
        
        # Используем временный файл для аутентификации
        creds = Credentials.from_service_account_file(temp_file, scopes=SCOPES)
        gc = gspread.authorize(creds)

        # Открываем таблицу
        spreadsheet = gc.open(SPREADSHEET_NAME)

        # Лист заказов
        try:
            worksheet_orders = spreadsheet.worksheet("Orders")
        except gspread.WorksheetNotFound:
            worksheet_orders = spreadsheet.add_worksheet(title="Orders", rows="1000", cols="20")
            headers = ["ID", "User ID", "Nickname", "Username Link", "Subscription", "Start Date", "End Date", "Created At", "Status"]
            worksheet_orders.append_row(headers)

        # Лист назначений сотрудников
        try:
            worksheet_assignments = spreadsheet.worksheet("Assignments")
        except gspread.WorksheetNotFound:
            worksheet_assignments = spreadsheet.add_worksheet(title="Assignments", rows="1000", cols="20")
            headers = ["Order ID", "Staff ID", "Staff Name", "Staff Username", "Assigned At", "Status"]
            worksheet_assignments.append_row(headers)

        # Лист сотрудников
        try:
            worksheet_staff = spreadsheet.worksheet("Staff")
        except gspread.WorksheetNotFound:
            worksheet_staff = spreadsheet.add_worksheet(title="Staff", rows="1000", cols="20")
            headers = ["User ID", "Name", "Username", "Position", "Added At", "Added By", "Status"]
            worksheet_staff.append_row(headers)
            worksheet_staff.append_row([841285005, "Denis_Kingsman", "admin", "Администратор", datetime.now().strftime("%d.%m.%Y %H:%M"), "system", "active"])

        sheets_enabled = True
        print("✅ Google Sheets успешно инициализирована")
        
        # Удаляем временный файл
        try:
            os.remove(temp_file)
        except:
            pass
            
        return True

    except Exception as e:
        print(f"❌ Ошибка инициализации Google Sheets: {e}")
        return False


# --- Загрузка сотрудников из Google Sheets ---
async def load_staff_from_sheets():
    """Загрузка сотрудников из Google Sheets"""
    global STAFF_MEMBERS
    try:
        if not sheets_enabled:
            print("❌ Google Sheets не инициализирована")
            return {}

        all_records = worksheet_staff.get_all_records()
        staff_members = {}

        for record in all_records:
            if record.get("User ID") and record.get("Status") == "active":
                user_id = int(record["User ID"])
                staff_members[user_id] = {
                    "name": record["Name"],
                    "username": record.get("Username", ""),
                    "position": record.get("Position", "Сотрудник")
                }

        STAFF_MEMBERS = staff_members
        print(f"✅ Загружено {len(STAFF_MEMBERS)} сотрудников из Google Sheets")
        return staff_members
    except Exception as e:
        print(f"❌ Ошибка при загрузке сотрудников: {e}")
        return {}


# --- Работа с сотрудниками ---
async def add_staff_member(user_id, name, username, position, added_by):
    """Добавление нового сотрудника"""
    try:
        if not sheets_enabled:
            return False, "❌ Google Sheets не подключена"

        existing_staff = await get_staff_member(user_id)
        if existing_staff:
            return False, f"❌ Сотрудник с ID {user_id} уже существует"

        worksheet_staff.append_row([
            user_id, name, username, position,
            datetime.now().strftime("%d.%m.%Y %H:%M"), added_by, "active"
        ])

        await load_staff_from_sheets()
        return True, f"✅ Сотрудник {name} (@{username}) успешно добавлен как {position}"
    except Exception as e:
        print(f"❌ Ошибка при добавлении сотрудника: {e}")
        return False, f"❌ Ошибка при добавлении сотрудника: {e}"


async def update_staff_position(user_id, new_position, updated_by):
    """Обновление должности сотрудника"""
    try:
        if not sheets_enabled:
            return False, "❌ Google Sheets не подключена"

        cell = worksheet_staff.find(str(user_id))
        if not cell:
            return False, f"❌ Сотрудник с ID {user_id} не найден"

        worksheet_staff.update_cell(cell.row, 4, new_position)
        await load_staff_from_sheets()

        staff_name = STAFF_MEMBERS.get(user_id, {}).get("name", "Неизвестный")
        return True, f"✅ Должность сотрудника {staff_name} изменена на: {new_position}"
    except Exception as e:
        print(f"❌ Ошибка при обновлении должности: {e}")
        return False, f"❌ Ошибка при обновлении должности: {e}"


async def remove_staff_member(user_id, removed_by):
    """Удаление сотрудника"""
    try:
        if not sheets_enabled:
            return False, "❌ Google Sheets не подключена"

        cell = worksheet_staff.find(str(user_id))
        if not cell:
            return False, f"❌ Сотрудник с ID {user_id} не найден"

        worksheet_staff.update_cell(cell.row, 7, "inactive")
        await load_staff_from_sheets()

        staff_name = STAFF_MEMBERS.get(user_id, {}).get("name", "Неизвестный")
        return True, f"✅ Сотрудник {staff_name} удален из системы"
    except Exception as e:
        print(f"❌ Ошибка при удалении сотрудника: {e}")
        return False, f"❌ Ошибка при удалении сотрудника: {e}"


async def get_staff_member(user_id):
    """Получение информации о сотруднике"""
    try:
        if not sheets_enabled:
            return None

        cell = worksheet_staff.find(str(user_id))
        if cell:
            row = worksheet_staff.row_values(cell.row)
            return {
                "user_id": row[0], "name": row[1], "username": row[2], "position": row[3],
                "added_at": row[4], "added_by": row[5], "status": row[6]
            }
        return None
    except Exception as e:
        print(f"❌ Ошибка при получении сотрудника: {e}")
        return None


# --- Работа с заказами ---
async def get_all_orders():
    """Получение всех заказов из Google Sheets"""
    try:
        if not sheets_enabled:
            print("❌ Google Sheets не инициализирована")
            return []

        all_records = worksheet_orders.get_all_records()
        orders = []

        for record in all_records:
            if record.get("ID"):
                orders.append({
                    "id": record["ID"], "user_id": int(record["User ID"]), "nickname": record["Nickname"],
                    "username_link": record["Username Link"], "subscription": record["Subscription"],
                    "start": record["Start Date"], "end": record["End Date"], "status": record.get("Status", "pending")
                })

        print(f"✅ Загружено {len(orders)} заказов из Google Sheets")
        return orders
    except Exception as e:
        print(f"❌ Ошибка при загрузке заказов: {e}")
        return []


async def save_order_to_sheets(order_data):
    """Сохранение заказа в Google Sheets"""
    try:
        if not sheets_enabled:
            return False

        worksheet_orders.append_row([
            order_data["id"], order_data["user_id"], order_data["nickname"],
            order_data["username_link"], order_data["subscription"],
            order_data["start"], order_data["end"],
            datetime.now().strftime("%d.%m.%Y %H:%M"), "pending"
        ])

        print(f"✅ Заказ {order_data['id']} сохранен в Google Sheets")
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении заказа: {e}")
        return False


async def update_order_status(order_id, status):
    """Обновление статуса заказа"""
    try:
        if not sheets_enabled:
            return False

        cell = worksheet_orders.find(order_id)
        if cell:
            worksheet_orders.update_cell(cell.row, 9, status)
            print(f"✅ Статус заказа {order_id} обновлен на: {status}")
            return True
        return False
    except Exception as e:
        print(f"❌ Ошибка при обновлении статуса: {e}")
        return False


async def assign_order_to_staff(order_id, staff_id, staff_name, staff_username):
    """Назначение заказа сотруднику"""
    try:
        if not sheets_enabled:
            return False

        worksheet_assignments.append_row([
            order_id, staff_id, staff_name, staff_username,
            datetime.now().strftime("%d.%m.%Y %H:%M"), "in_progress"
        ])

        print(f"✅ Заказ {order_id} назначен сотруднику {staff_name} (@{staff_username})")
        return True
    except Exception as e:
        print(f"❌ Ошибка при назначении заказа: {e}")
        return False


async def get_order_assignment(order_id):
    """Получение информации о назначении заказа"""
    try:
        if not sheets_enabled:
            return None

        cell = worksheet_assignments.find(order_id)
        if cell:
            row = worksheet_assignments.row_values(cell.row)
            return {
                "order_id": row[0], "staff_id": row[1], "staff_name": row[2],
                "staff_username": row[3], "assigned_at": row[4], "status": row[5]
            }
        return None
    except Exception as e:
        print(f"❌ Ошибка при получении назначения: {e}")
        return None


async def get_user_active_orders(user_id):
    """Получение активных заказов пользователя"""
    try:
        orders = await get_all_orders()
        active_orders = []
        today = datetime.now().date()

        for order in orders:
            if order["user_id"] == user_id:
                try:
                    end_date = datetime.strptime(order["end"], "%d.%m.%Y").date()
                    if end_date >= today:
                        active_orders.append(order)
                except ValueError:
                    continue

        return active_orders
    except Exception as e:
        print(f"❌ Ошибка при получении заказов пользователя: {e}")
        return []


async def can_user_create_order(user_id, username_link):
    """Проверяет, может ли пользователь создать новый заказ"""
    try:
        user_orders = []
        all_orders = await get_all_orders()

        for order in all_orders:
            if order["user_id"] == user_id or order["username_link"] == username_link:
                user_orders.append(order)

        if not user_orders:
            return True, None

        active_orders = []
        today = datetime.now().date()

        for order in user_orders:
            try:
                end_date = datetime.strptime(order["end"], "%d.%m.%Y").date()
                days_until_end = (end_date - today).days
                if days_until_end >= 0:
                    active_orders.append((order, days_until_end))
            except ValueError:
                continue

        if not active_orders:
            return True, None

        latest_order = max(active_orders, key=lambda x: datetime.strptime(x[0]["end"], "%d.%m.%Y"))
        order_data, days_until_end = latest_order

        if days_until_end > 1:
            return False, f"❌ У вас уже есть активный абонемент '{order_data['subscription']}', который действует до {order_data['end']}.\n\nВы можете оформить новый абонемент за 1 день до окончания текущего."
        elif days_until_end == 1:
            return True, f"⚠️ Ваш текущий абонемент '{order_data['subscription']}' заканчивается завтра ({order_data['end']}). Вы можете оформить новый абонемент."
        else:
            return True, f"⚠️ Ваш текущий абонемент '{order_data['subscription']}' заканчивается сегодня. Вы можете оформить новый абонемент."

    except Exception as e:
        print(f"❌ Ошибка при проверке возможности создания заказа: {e}")
        return True, None


def validate_nickname(nickname):
    """Проверяет формат ника: должен содержать нижнее подчеркивание"""
    if "_" not in nickname:
        return False, "❌ Неправильный формат ника! Ник должен содержать нижнее подчеркивание (_).\n\nПример правильного формата: Denis_Kingsman\n\nПожалуйста, введите ваш игровой ник в правильном формате:"

    if len(nickname) < 3:
        return False, "❌ Слишком короткий ник! Ник должен содержать минимум 3 символа."

    if len(nickname) > 20:
        return False, "❌ Слишком длинный ник! Ник должен содержать максимум 20 символов."

    if not re.match(r'^[a-zA-Z0-9_]+$', nickname):
        return False, "❌ Ник содержит недопустимые символы! Разрешены только буквы (a-z, A-Z), цифры (0-9) и нижнее подчеркивание (_)."

    return True, "✅ Формат ника правильный!"


# --- Клавиатуры ---
def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Оформить заказ", callback_data="start_order")],
        [InlineKeyboardButton(text="🛠 Техническая поддержка", callback_data="support_start")]
    ])


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Эконом", callback_data="econom")],
        [InlineKeyboardButton(text="🚘 Стандарт", callback_data="standard")],
        [InlineKeyboardButton(text="🚙 Комфорт", callback_data="comfort")],
        [InlineKeyboardButton(text="🏎 Премиум", callback_data="premium")]
    ])


def confirmation_keyboard(order_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{order_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{order_id}")
        ]
    ])


def staff_actions_keyboard(order_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Взять заказ", callback_data=f"take_order_{order_id}")]
    ])


# --- Команды бота ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(
        "👋 Привет! Добро пожаловать в Kingsman Rent.\nВыберите действие:",
        reply_markup=start_keyboard()
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    print(f"🔧 Получена команда /status от пользователя {message.from_user.id}")

    orders = await get_all_orders()
    today = datetime.now().date()
    active_orders = 0
    pending_orders = 0
    assigned_orders = 0

    for order in orders:
        try:
            if order["status"] == "assigned":
                assigned_orders += 1
            elif order["status"] == "pending":
                pending_orders += 1

            end_date = datetime.strptime(order["end"], "%d.%m.%Y").date()
            if end_date >= today:
                active_orders += 1
        except ValueError:
            continue

    storage_type = "Google Sheets" if sheets_enabled else "❌ Не подключена"

    status_text = (
        f"🤖 Статус бота Kingsman Rent:\n"
        f"📊 Всего заказов: {len(orders)}\n"
        f"🟢 Активных абонементов: {active_orders}\n"
        f"💾 Хранилище: {storage_type}\n"
        f"👥 Сотрудников: {len(STAFF_MEMBERS)}"
    )

    if message.from_user.id in ADMIN_IDS:
        status_text += f"\n\n👤 Активных сессий: {len(player_data)}"
        status_text += f"\n🆘 Обращений в поддержку: {len(support_requests)}"
        status_text += f"\n🔧 Режим отладки: Администратор"

    await message.answer(status_text)
    print(f"✅ Отправлен статус пользователю {message.from_user.id}")


# --- Остальные обработчики остаются без изменений ---
# [Здесь должен быть остальной код обработчиков, который не изменялся]
# Для экономии места оставлю только основные функции

@dp.callback_query(F.data == "start_order")
async def ask_nickname(callback: CallbackQuery):
    user_id = callback.from_user.id
    username_link = f"https://t.me/{callback.from_user.username}" if callback.from_user.username else "Нет ссылки"
    can_create, message_text = await can_user_create_order(user_id, username_link)

    if not can_create:
        await callback.message.answer(message_text)
        await callback.answer()
        return

    if message_text and "можно оформить" in message_text:
        await callback.message.answer(message_text)

    player_data[user_id] = {"stage": "waiting_nickname"}
    await callback.message.answer(
        "✍️ Введите ваш игровой ник:\n\n"
        "⚠️ <b>Формат ника должен содержать нижнее подчеркивание (_)</b>\n"
        "📝 <b>Пример правильного формата:</b> <code>Ivan_Ivanov</code>\n\n"
        "Пожалуйста, введите ваш ник:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.in_(["econom", "standard", "comfort", "premium"]))
async def process_order(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = player_data.get(user_id)
    if not data or data.get("stage") != "choose_subscription":
        await callback.answer("Сначала введи игровой ник /start", show_alert=True)
        return

    subscription_names = {
        "econom": "Эконом", "standard": "Стандарт", 
        "comfort": "Комфорт", "premium": "Премиум"
    }

    chosen = callback.data
    nickname = data["nickname"]
    username_link = data["username_link"]

    can_create, message_text = await can_user_create_order(user_id, username_link)
    if not can_create:
        await callback.message.answer(message_text)
        await callback.answer()
        return

    order_id = str(uuid.uuid4())[:8]
    start_date = datetime.now()
    end_date = start_date + timedelta(days=7)

    order_confirmations[order_id] = {
        "user_id": user_id, "nickname": nickname, "username_link": username_link,
        "subscription": subscription_names[chosen], "start": start_date.strftime("%d.%m.%Y"),
        "end": end_date.strftime("%d.%m.%Y"), "callback_message": callback.message
    }

    confirm_text = (
        f"📋 Подтвердите заказ:\n\n"
        f"👤 Игровой ник: {nickname}\n"
        f"🚘 Абонемент: {subscription_names[chosen]}\n"
        f"📅 Срок действия: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}\n\n"
        f"🆔 ID заказа: {order_id}"
    )

    await callback.message.answer(confirm_text, reply_markup=confirmation_keyboard(order_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_order(callback: CallbackQuery):
    order_id = callback.data.replace("confirm_", "")

    if order_id not in order_confirmations:
        await callback.answer("❌ Заказ не найден или устарел", show_alert=True)
        return

    order_data = order_confirmations[order_id]
    success = await save_order_to_sheets({
        "id": order_id, "user_id": order_data["user_id"], "nickname": order_data["nickname"],
        "username_link": order_data["username_link"], "subscription": order_data["subscription"],
        "start": order_data["start"], "end": order_data["end"]
    })

    if not success:
        await callback.answer("❌ Ошибка при сохранении заказа", show_alert=True)
        return

    order_text = (
        f"📦 Новый заказ\n"
        f"👤 Игровой ник: {order_data['nickname']}\n"
        f"🔗 Ссылка: {order_data['username_link']}\n"
        f"🚘 Абонемент: {order_data['subscription']}\n"
        f"📅 Начало: {order_data['start']}\n"
        f"📆 Окончание: {order_data['end']}\n"
        f"🆔 ID заказа: {order_id}\n"
        f"🕐 Создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    await bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ORDERS,
        text=order_text,
        reply_markup=staff_actions_keyboard(order_id)
    )

    await callback.message.edit_text(
        f"✅ Заказ подтвержден!\n\n"
        f"👤 Ник: {order_data['nickname']}\n"
        f"🚘 Абонемент: {order_data['subscription']}\n"
        f"📅 Срок: {order_data['start']} — {order_data['end']}\n"
        f"🆔 ID: {order_id}\n\n"
        f"Ожидайте, в ближайшее время с вами свяжется наш менеджер."
    )

    del order_confirmations[order_id]
    await callback.answer()


@dp.callback_query(F.data.startswith("take_order_"))
async def take_order(callback: CallbackQuery):
    staff_id = callback.from_user.id
    if staff_id not in STAFF_MEMBERS:
        await callback.answer("❌ Только для сотрудников", show_alert=True)
        return

    order_id = callback.data.replace("take_order_", "")
    staff_data = STAFF_MEMBERS.get(staff_id, {})
    staff_name = staff_data.get("name", "Неизвестный сотрудник")
    staff_username = staff_data.get("username", "")

    if staff_username:
        safe_staff_name = html.escape(staff_name)
        staff_display = f'<a href="https://t.me/{staff_username}">{safe_staff_name}</a>'
    else:
        staff_display = html.escape(staff_name)

    success = await assign_order_to_staff(order_id, staff_id, staff_name, staff_username)
    if not success:
        await callback.answer("❌ Ошибка при взятии заказа", show_alert=True)
        return

    await update_order_status(order_id, "assigned")
    original_text = callback.message.text
    current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
    updated_text = original_text + f"\n\n👨‍💼 Заказ взят: {staff_display}\n⏰ Взято в работу: {current_time}"

    await callback.message.edit_text(updated_text, parse_mode="HTML", reply_markup=None)
    await callback.answer(f"✅ Вы взяли заказ {order_id} в работу")


# --- Запуск ---
async def main():
    print("🤖 Запуск бота...")

    if not BOT_TOKEN:
        print("❌ Критическая ошибка: BOT_TOKEN не установлен!")
        return
        
    if not SERVICE_ACCOUNT_JSON:
        print("❌ Критическая ошибка: SERVICE_ACCOUNT_JSON не установлен!")
        return

    if not init_google_sheets():
        print("❌ Критическая ошибка: Не удалось подключиться к Google Sheets!")
        return

    await load_staff_from_sheets()
    test_orders = await get_all_orders()
    print(f"✅ Подключение установлено. Заказов в таблице: {len(test_orders)}")
    print(f"👥 Сотрудников в системе: {len(STAFF_MEMBERS)}")

    print("✅ Бот запущен и готов к работе")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("❌ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
