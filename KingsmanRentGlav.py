import asyncio
import uuid
import re
import html
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

# 🔧 Настройки
BOT_TOKEN = "8148697332:AAGy6r-GNzqVYabKCQIlfQI-gCkbelQucFM"
GROUP_ID = -1002773883024
TOPIC_ORDERS = 81003
TOPIC_SUPPORT = 81451
ADMIN_IDS = [841285005]

# Сотрудники будут загружаться из Google Sheets
STAFF_MEMBERS = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Настройки Google Sheets ---
SERVICE_ACCOUNT_FILE = 'service_account.json'
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
order_confirmations = {}  # Для хранения подтверждений
staff_management_data = {}  # Для управления сотрудниками


# --- Инициализация Google Sheets ---
def init_google_sheets():
    """Инициализация Google Sheets"""
    global creds, gc, worksheet_orders, worksheet_assignments, worksheet_staff, sheets_enabled
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)

        # Открываем таблицу
        spreadsheet = gc.open(SPREADSHEET_NAME)

        # Лист заказов
        try:
            worksheet_orders = spreadsheet.worksheet("Orders")
        except gspread.WorksheetNotFound:
            worksheet_orders = spreadsheet.add_worksheet(title="Orders", rows="1000", cols="20")
            headers = [
                "ID", "User ID", "Nickname", "Username Link",
                "Subscription", "Start Date", "End Date", "Created At", "Status"
            ]
            worksheet_orders.append_row(headers)

        # Лист назначений сотрудников
        try:
            worksheet_assignments = spreadsheet.worksheet("Assignments")
        except gspread.WorksheetNotFound:
            worksheet_assignments = spreadsheet.add_worksheet(title="Assignments", rows="1000", cols="20")
            headers = [
                "Order ID", "Staff ID", "Staff Name", "Staff Username",
                "Assigned At", "Status"
            ]
            worksheet_assignments.append_row(headers)

        # Лист сотрудников
        try:
            worksheet_staff = spreadsheet.worksheet("Staff")
        except gspread.WorksheetNotFound:
            worksheet_staff = spreadsheet.add_worksheet(title="Staff", rows="1000", cols="20")
            headers = [
                "User ID", "Name", "Username", "Position",
                "Added At", "Added By", "Status"
            ]
            worksheet_staff.append_row(headers)
            # Добавляем главного администратора по умолчанию
            worksheet_staff.append_row([
                841285005, "Denis_Kingsman", "admin", "Администратор",
                datetime.now().strftime("%d.%m.%Y %H:%M"), "system", "active"
            ])

        sheets_enabled = True
        print("✅ Google Sheets успешно инициализирована")
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

        # Проверяем, существует ли уже сотрудник
        existing_staff = await get_staff_member(user_id)
        if existing_staff:
            return False, f"❌ Сотрудник с ID {user_id} уже существует"

        worksheet_staff.append_row([
            user_id,
            name,
            username,
            position,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            added_by,
            "active"
        ])

        # Обновляем кэш
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

        # Обновляем должность (столбец D, индекс 4)
        worksheet_staff.update_cell(cell.row, 4, new_position)

        # Обновляем кэш
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

        # Помечаем как неактивного (столбец G, индекс 7)
        worksheet_staff.update_cell(cell.row, 7, "inactive")

        # Обновляем кэш
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
                "user_id": row[0],
                "name": row[1],
                "username": row[2],
                "position": row[3],
                "added_at": row[4],
                "added_by": row[5],
                "status": row[6]
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
                    "id": record["ID"],
                    "user_id": int(record["User ID"]),
                    "nickname": record["Nickname"],
                    "username_link": record["Username Link"],
                    "subscription": record["Subscription"],
                    "start": record["Start Date"],
                    "end": record["End Date"],
                    "status": record.get("Status", "pending")
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
            order_data["id"],
            order_data["user_id"],
            order_data["nickname"],
            order_data["username_link"],
            order_data["subscription"],
            order_data["start"],
            order_data["end"],
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            "pending"  # Статус по умолчанию
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
            # Обновляем статус (столбец I, индекс 8)
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
            order_id,
            staff_id,
            staff_name,
            staff_username,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            "in_progress"
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
            # Получаем всю строку назначения
            row = worksheet_assignments.row_values(cell.row)
            return {
                "order_id": row[0],
                "staff_id": row[1],
                "staff_name": row[2],
                "staff_username": row[3],
                "assigned_at": row[4],
                "status": row[5]
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
                    # Считаем заказ активным, если дата окончания >= сегодня
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
        # Получаем все заказы пользователя
        user_orders = []
        all_orders = await get_all_orders()

        for order in all_orders:
            if order["user_id"] == user_id or order["username_link"] == username_link:
                user_orders.append(order)

        if not user_orders:
            return True, None  # Нет заказов - можно создавать

        # Проверяем активные заказы
        active_orders = []
        today = datetime.now().date()

        for order in user_orders:
            try:
                end_date = datetime.strptime(order["end"], "%d.%m.%Y").date()
                # Считаем заказ активным, если до окончания осталось 1 день или больше
                days_until_end = (end_date - today).days
                if days_until_end >= 0:  # Активен сегодня или в будущем
                    active_orders.append((order, days_until_end))
            except ValueError:
                continue

        if not active_orders:
            return True, None  # Нет активных заказов - можно создавать

        # Находим заказ с максимальной датой окончания
        latest_order = max(active_orders, key=lambda x: datetime.strptime(x[0]["end"], "%d.%m.%Y"))
        order_data, days_until_end = latest_order

        if days_until_end > 1:
            return False, f"❌ У вас уже есть активный абонемент '{order_data['subscription']}', который действует до {order_data['end']}.\n\nВы можете оформить новый абонемент за 1 день до окончания текущего."
        elif days_until_end == 1:
            return True, f"⚠️ Ваш текущий абонемент '{order_data['subscription']}' заканчивается завтра ({order_data['end']}). Вы можете оформить новый абонемент."
        else:  # days_until_end == 0
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

    # Проверяем на допустимые символы (буквы, цифры, нижнее подчеркивание)
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
    """Клавиатура подтверждения заказа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{order_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{order_id}")
        ]
    ])


def staff_actions_keyboard(order_id) -> InlineKeyboardMarkup:
    """Клавиатура действий для сотрудников - ПРОСТО КНОПКА ВЗЯТЬ ЗАКАЗ"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Взять заказ",
            callback_data=f"take_order_{order_id}"
        )]
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
    """Команда статуса бота - работает для всех"""
    print(f"🔧 Получена команда /status от пользователя {message.from_user.id}")

    # Получаем статистику напрямую из Google Sheets
    orders = await get_all_orders()

    # Считаем статистику
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

    # Базовая информация для всех пользователей
    status_text = (
        f"🤖 Статус бота Kingsman Rent:\n"
        f"📊 Всего заказов: {len(orders)}\n"
        f"🟢 Активных абонементов: {active_orders}\n"
        f"💾 Хранилище: {storage_type}\n"
        f"👥 Сотрудников: {len(STAFF_MEMBERS)}"
    )

    # Дополнительная информация для администраторов
    if message.from_user.id in ADMIN_IDS:
        status_text += f"\n\n👤 Активных сессий: {len(player_data)}"
        status_text += f"\n🆘 Обращений в поддержку: {len(support_requests)}"
        status_text += f"\n🔧 Режим отладки: Администратор"

    await message.answer(status_text)
    print(f"✅ Отправлен статус пользователю {message.from_user.id}")


# --- Команды управления сотрудниками ---
@dp.message(Command("add_staff"))
async def cmd_add_staff(message: Message):
    """Добавление сотрудника - начало процесса"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    staff_management_data[message.from_user.id] = {
        "stage": "waiting_staff_user_id",
        "action": "add"
    }

    await message.answer(
        "➕ Добавление нового сотрудника\n\n"
        "Введите User ID нового сотрудника (числовой идентификатор):\n\n"
        "💡 Как получить User ID?\n"
        "1. Попросите сотрудника написать боту команду /myid\n"
        "2. Скопируйте его User ID из ответа"
    )


@dp.message(Command("set_position"))
async def cmd_set_position(message: Message):
    """Изменение должности сотрудника - начало процесса"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    staff_management_data[message.from_user.id] = {
        "stage": "waiting_staff_user_id",
        "action": "set_position"
    }

    await message.answer(
        "✏️ Изменение должности сотрудника\n\n"
        "Введите User ID сотрудника (числовой идентификатор):"
    )


@dp.message(Command("remove_staff"))
async def cmd_remove_staff(message: Message):
    """Удаление сотрудника - начало процесса"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    staff_management_data[message.from_user.id] = {
        "stage": "waiting_staff_user_id",
        "action": "remove"
    }

    await message.answer(
        "🗑️ Удаление сотрудника\n\n"
        "Введите User ID сотрудника (числовой идентификатор):"
    )


@dp.message(Command("list_staff"))
async def cmd_list_staff(message: Message):
    """Показать список всех сотрудников"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    if not STAFF_MEMBERS:
        await message.answer("📭 В системе нет сотрудников.")
        return

    staff_list = "👥 Список сотрудников:\n\n"
    for i, (user_id, staff_data) in enumerate(STAFF_MEMBERS.items(), 1):
        username_display = f"@{staff_data['username']}" if staff_data['username'] else "нет username"
        staff_list += (
            f"{i}. 👤 {staff_data['name']}\n"
            f"   📱 {username_display}\n"
            f"   💼 {staff_data['position']}\n"
            f"   🆔 ID: {user_id}\n\n"
        )

    await message.answer(staff_list)


# --- Обработка ввода для управления сотрудниками ---
@dp.message(F.text)
async def handle_text(message: Message):
    if message.chat.type != "private":
        return

    user_id = message.from_user.id

    # Проверяем, находится ли пользователь в процессе управления сотрудниками
    staff_management_entry = staff_management_data.get(user_id)
    if staff_management_entry:
        await handle_staff_management(message, staff_management_entry)
        return

    # Обработка обычных сообщений (заказы, поддержка)
    user_entry = player_data.get(user_id)
    if not user_entry:
        return

    if user_entry.get("stage") == "waiting_nickname":
        nickname = message.text.strip()

        # Проверяем формат ника
        is_valid, validation_message = validate_nickname(nickname)

        if not is_valid:
            await message.answer(validation_message)
            return

        username_link = f"https://t.me/{message.from_user.username}" if message.from_user.username else "Нет ссылки"

        # Еще раз проверяем возможность создания заказа (на случай, если прошло время)
        can_create, message_text = await can_user_create_order(user_id, username_link)

        if not can_create:
            await message.answer(message_text)
            player_data.pop(user_id, None)
            return

        player_data[user_id] = {
            "stage": "choose_subscription",
            "nickname": nickname,
            "username_link": username_link
        }
        await message.answer(
            f"✅ Отлично, {nickname}! Теперь выбери абонемент:",
            reply_markup=subscription_keyboard()
        )

    elif user_entry.get("stage") == "waiting_issue":
        nickname = user_entry.get("nickname")
        subscription = user_entry.get("subscription")
        end_date = user_entry.get("end")
        username_link = f"https://t.me/{message.from_user.username}" if message.from_user.username else "Нет ссылки"
        issue_text = message.text.strip()
        issue_id = str(uuid.uuid4())[:8]
        date_now = datetime.now().strftime("%d.%m.%Y %H:%M")

        support_requests.append({
            "id": issue_id,
            "user_id": user_id,
            "nickname": nickname,
            "username_link": username_link,
            "subscription": subscription,
            "end": end_date,
            "issue": issue_text,
            "date": date_now
        })

        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_SUPPORT,
            text=(
                f"🆘 Новое обращение в техподдержку\n"
                f"👤 Игровой ник: {nickname}\n"
                f"🔗 Ссылка: {username_link}\n"
                f"🚘 Абонемент: {subscription}\n"
                f"📆 Действует до: {end_date}\n"
                f"💬 Проблема: {issue_text}\n"
                f"📅 Дата: {date_now}\n"
                f"🆔 ID обращения: {issue_id}"
            )
        )
        await message.answer("✅ Спасибо! Ваше обращение отправлено, ожидайте ответа.")
        player_data.pop(user_id, None)


async def handle_staff_management(message: Message, management_data):
    """Обработка ввода для управления сотрудниками"""
    user_id = message.from_user.id
    text = message.text.strip()

    if management_data["stage"] == "waiting_staff_user_id":
        try:
            staff_user_id = int(text)
            management_data["staff_user_id"] = staff_user_id

            if management_data["action"] == "add":
                management_data["stage"] = "waiting_staff_name"
                await message.answer(
                    "✅ User ID принят\n\n"
                    "Теперь введите имя сотрудника:"
                )
            elif management_data["action"] == "set_position":
                # Проверяем существование сотрудника
                staff_info = await get_staff_member(staff_user_id)
                if not staff_info:
                    await message.answer(f"❌ Сотрудник с ID {staff_user_id} не найден.")
                    staff_management_data.pop(user_id, None)
                    return

                management_data["stage"] = "waiting_staff_position"
                await message.answer(
                    f"✅ Сотрудник найден: {staff_info['name']}\n\n"
                    "Введите новую должность сотрудника:"
                )
            elif management_data["action"] == "remove":
                # Проверяем существование сотрудника
                staff_info = await get_staff_member(staff_user_id)
                if not staff_info:
                    await message.answer(f"❌ Сотрудник с ID {staff_user_id} не найден.")
                    staff_management_data.pop(user_id, None)
                    return

                # Удаляем сотрудника
                success, result_message = await remove_staff_member(staff_user_id, user_id)
                await message.answer(result_message)
                staff_management_data.pop(user_id, None)

        except ValueError:
            await message.answer("❌ Неверный формат User ID! Введите числовой идентификатор.")

    elif management_data["stage"] == "waiting_staff_name":
        management_data["staff_name"] = text
        management_data["stage"] = "waiting_staff_username"
        await message.answer(
            "✅ Имя принято\n\n"
            "Теперь введите username сотрудника (без @):"
        )

    elif management_data["stage"] == "waiting_staff_username":
        management_data["staff_username"] = text
        management_data["stage"] = "waiting_staff_position"
        await message.answer(
            "✅ Username принят\n\n"
            "Теперь введите должность сотрудника:"
        )

    elif management_data["stage"] == "waiting_staff_position":
        position = text

        if management_data["action"] == "add":
            # Добавляем сотрудника
            success, result_message = await add_staff_member(
                management_data["staff_user_id"],
                management_data["staff_name"],
                management_data["staff_username"],
                position,
                user_id
            )
            await message.answer(result_message)

        elif management_data["action"] == "set_position":
            # Обновляем должность
            success, result_message = await update_staff_position(
                management_data["staff_user_id"],
                position,
                user_id
            )
            await message.answer(result_message)

        staff_management_data.pop(user_id, None)


# --- Остальные обработчики (заказы, поддержка, назначения) ---
@dp.callback_query(F.data == "start_order")
async def ask_nickname(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем, может ли пользователь создать заказ
    username_link = f"https://t.me/{callback.from_user.username}" if callback.from_user.username else "Нет ссылки"
    can_create, message_text = await can_user_create_order(user_id, username_link)

    if not can_create:
        await callback.message.answer(message_text)
        await callback.answer()
        return

    if message_text and "можно оформить" in message_text:
        await callback.message.answer(message_text)

    player_data[user_id] = {"stage": "waiting_nickname"}

    # Объясняем формат ника
    await callback.message.answer(
        "✍️ Введите ваш игровой ник:\n\n"
        "⚠️ <b>Формат ника должен содержать нижнее подчеркивание (_)</b>\n"
        "📝 <b>Пример правильного формата:</b> <code>Ivan_Ivanov</code>\n\n"
        "Пожалуйста, введите ваш ник:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "support_start")
async def start_support(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Получаем активные заказы пользователя напрямую из Google Sheets
    active_orders = await get_user_active_orders(user_id)

    if not active_orders:
        await callback.message.answer(
            "❌ У вас нет активного абонемента. Оформите заказ, чтобы обратиться в поддержку."
        )
        await callback.answer()
        return

    # Берем первый активный заказ
    active_order = active_orders[0]
    player_data[user_id] = {
        "stage": "waiting_issue",
        "nickname": active_order["nickname"],
        "subscription": active_order["subscription"],
        "end": active_order["end"]
    }
    await callback.message.answer(
        "🛠 Опишите вашу проблему, и мы постараемся помочь как можно скорее:"
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
        "econom": "Эконом",
        "standard": "Стандарт",
        "comfort": "Комфорт",
        "premium": "Премиум"
    }

    chosen = callback.data
    nickname = data["nickname"]
    username_link = data["username_link"]

    # Финальная проверка перед сохранением
    can_create, message_text = await can_user_create_order(user_id, username_link)
    if not can_create:
        await callback.message.answer(message_text)
        await callback.answer()
        return

    order_id = str(uuid.uuid4())[:8]
    start_date = datetime.now()
    end_date = start_date + timedelta(days=7)

    # Сохраняем данные для подтверждения
    order_confirmations[order_id] = {
        "user_id": user_id,
        "nickname": nickname,
        "username_link": username_link,
        "subscription": subscription_names[chosen],
        "start": start_date.strftime("%d.%m.%Y"),
        "end": end_date.strftime("%d.%m.%Y"),
        "callback_message": callback.message
    }

    # Показываем подтверждение
    confirm_text = (
        f"📋 Подтвердите заказ:\n\n"
        f"👤 Игровой ник: {nickname}\n"
        f"🚘 Абонемент: {subscription_names[chosen]}\n"
        f"📅 Срок действия: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}\n\n"
        f"🆔 ID заказа: {order_id}"
    )

    await callback.message.answer(
        confirm_text,
        reply_markup=confirmation_keyboard(order_id)
    )
    await callback.answer()


# --- Обработка подтверждения заказа ---
@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_order(callback: CallbackQuery):
    order_id = callback.data.replace("confirm_", "")

    if order_id not in order_confirmations:
        await callback.answer("❌ Заказ не найден или устарел", show_alert=True)
        return

    order_data = order_confirmations[order_id]

    # Сохраняем заказ в Google Sheets
    success = await save_order_to_sheets({
        "id": order_id,
        "user_id": order_data["user_id"],
        "nickname": order_data["nickname"],
        "username_link": order_data["username_link"],
        "subscription": order_data["subscription"],
        "start": order_data["start"],
        "end": order_data["end"]
    })

    if not success:
        await callback.answer("❌ Ошибка при сохранении заказа", show_alert=True)
        return

    # Отправляем сообщение в группу с кнопкой для сотрудников
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

    message = await bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ORDERS,
        text=order_text,
        reply_markup=staff_actions_keyboard(order_id)
    )

    # Обновляем сообщение с подтверждением
    await callback.message.edit_text(
        f"✅ Заказ подтвержден!\n\n"
        f"👤 Ник: {order_data['nickname']}\n"
        f"🚘 Абонемент: {order_data['subscription']}\n"
        f"📅 Срок: {order_data['start']} — {order_data['end']}\n"
        f"🆔 ID: {order_id}\n\n"
        f"Ожидайте, в ближайшее время с вами свяжется наш менеджер."
    )

    # Удаляем из временного хранилища
    del order_confirmations[order_id]
    await callback.answer()


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_order(callback: CallbackQuery):
    order_id = callback.data.replace("cancel_", "")

    if order_id in order_confirmations:
        del order_confirmations[order_id]

    await callback.message.edit_text("❌ Заказ отменен")
    await callback.answer()


# --- Обработка взятия заказа сотрудником ---
@dp.callback_query(F.data.startswith("take_order_"))
async def take_order(callback: CallbackQuery):
    """Новый обработчик взятия заказа сотрудником"""
    # Проверяем, является ли пользователь сотрудником
    staff_id = callback.from_user.id
    if staff_id not in STAFF_MEMBERS:
        await callback.answer("❌ Только для сотрудников", show_alert=True)
        return

    order_id = callback.data.replace("take_order_", "")

    # Получаем данные сотрудника
    staff_data = STAFF_MEMBERS.get(staff_id, {})
    staff_name = staff_data.get("name", "Неизвестный сотрудник")
    staff_username = staff_data.get("username", "")

    # Формируем ссылку на телеграм сотрудника в HTML формате
    if staff_username:
        # Экранируем имя сотрудника для HTML
        safe_staff_name = html.escape(staff_name)
        staff_display = f'<a href="https://t.me/{staff_username}">{safe_staff_name}</a>'
    else:
        staff_display = html.escape(staff_name)

    # Назначаем заказ сотруднику
    success = await assign_order_to_staff(order_id, staff_id, staff_name, staff_username)

    if not success:
        await callback.answer("❌ Ошибка при взятии заказа", show_alert=True)
        return

    # Обновляем статус заказа
    await update_order_status(order_id, "assigned")

    # Обновляем сообщение в группе
    original_text = callback.message.text

    # Добавляем информацию о сотруднике, который взял заказ
    current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
    updated_text = original_text + f"\n\n👨‍💼 Заказ взят: {staff_display}\n⏰ Взято в работу: {current_time}"

    # Убираем все кнопки после взятия заказа
    await callback.message.edit_text(
        updated_text,
        parse_mode="HTML",  # Используем HTML вместо Markdown
        reply_markup=None  # Убираем клавиатуру
    )

    await callback.answer(f"✅ Вы взяли заказ {order_id} в работу")


# --- Другие команды ---
@dp.message(Command("getid"))
async def cmd_getid(message: Message):
    await message.answer(f"Chat ID: {message.chat.id}\nUser ID: {message.from_user.id}")


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    is_staff = user_id in STAFF_MEMBERS
    admin_status = "✅ Администратор" if is_admin else "❌ Не администратор"
    staff_status = "✅ Сотрудник" if is_staff else "❌ Не сотрудник"

    await message.answer(
        f"👤 Ваш ID: {user_id}\n"
        f"🛡 Статус: {admin_status}\n"
        f"👨‍💼 Роль: {staff_status}\n"
        f"📋 ID администраторов: {ADMIN_IDS}"
    )


@dp.message(Command("my_orders"))
async def cmd_my_orders(message: Message):
    """Показать мои активные заказы"""
    user_id = message.from_user.id

    active_orders = await get_user_active_orders(user_id)

    if not active_orders:
        await message.answer("📭 У вас нет активных абонементов.")
        return

    orders_text = "📋 Ваши активные абонементы:\n\n"
    for i, order in enumerate(active_orders, 1):
        orders_text += (
            f"{i}. 🚘 {order['subscription']}\n"
            f"   👤 Ник: {order['nickname']}\n"
            f"   📅 Действует до: {order['end']}\n"
            f"   🆔 ID: {order['id']}\n\n"
        )

    await message.answer(orders_text)


@dp.message(Command("staff_orders"))
async def cmd_staff_orders(message: Message):
    """Показать заказы в работе у сотрудника"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для сотрудников.")
        return

    try:
        # Получаем все назначения
        all_records = worksheet_assignments.get_all_records()
        active_assignments = [r for r in all_records if r.get("Status") == "in_progress"]

        if not active_assignments:
            await message.answer("📭 Нет заказов в работе.")
            return

        assignments_text = "👨‍💼 Заказы в работе:\n\n"
        for i, assignment in enumerate(active_assignments, 1):
            staff_info = f"@{assignment['Staff Username']}" if assignment.get('Staff Username') else assignment[
                'Staff Name']
            assignments_text += (
                f"{i}. 🆔 {assignment['Order ID']}\n"
                f"   👤 Сотрудник: {staff_info}\n"
                f"   ⏰ Взят: {assignment['Assigned At']}\n\n"
            )

        await message.answer(assignments_text)

    except Exception as e:
        await message.answer(f"❌ Ошибка при получении данных: {e}")


@dp.message(Command("debug_orders"))
async def cmd_debug_orders(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    # Получаем заказы напрямую из Google Sheets
    orders = await get_all_orders()

    if not orders:
        await message.answer("📭 Нет заказов в Google Sheets.")
        return

    orders_list = "\n".join(
        [f"🆔 {o['id']} | 👤 {o['nickname']} | 🚘 {o['subscription']} | 📅 до {o['end']} | 📊 {o['status']}" for o in
         orders])
    await message.answer(
        f"📊 Всего заказов в Google Sheets: {len(orders)}\n\n{orders_list}"
    )


# --- Запуск ---
async def main():
    print("🤖 Запуск бота он просыпается уже...")

    # Инициализация Google Sheets
    if not init_google_sheets():
        print("❌ Критическая ошибка: Не удалось подключиться к Google Sheets!")
        print("📝 Бот не может работать без подключения к Google Sheets")
        return

    # Загружаем сотрудников
    await load_staff_from_sheets()

    # Проверяем подключение
    test_orders = await get_all_orders()
    print(f"✅ Подключение установлено. Заказов в таблице: {len(test_orders)}")
    print(f"👥 Сотрудников в системе: {len(STAFF_MEMBERS)}")

    print("✅ Бот запущен и готов к работе, проснулся xD")
    print("💡 Режим: Прямая работа с Google Sheets")
    print("🔧 Доступные команды: /start, /status, /my_orders, /staff")
    print("👥 Команды управления сотрудниками:")
    print("   /staff - меню управления сотрудниками")
    print("   /add_staff - добавить сотрудника")
    print("   /set_position - изменить должность")
    print("   /remove_staff - удалить сотрудника")
    print("   /list_staff - список сотрудников")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("❌ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")