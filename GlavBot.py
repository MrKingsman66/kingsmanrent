import os
import json
import base64
import asyncio
import uuid
import re
import html
import json
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
@@ -12,16 +14,27 @@
Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

# Импортируем конфигурацию
from config import BOT_TOKEN, GROUP_ID, TOPIC_ORDERS, TOPIC_SUPPORT, ADMIN_IDS, SCOPES, SPREADSHEET_NAME
from service_account_loader import load_service_account
# 🔧 Настройки
BOT_TOKEN = "8148697332:AAGy6r-GNzqVYabKCQIlfQI-gCkbelQucFM"
GROUP_ID = -1002773883024
TOPIC_ORDERS = 81003
TOPIC_SUPPORT = 81451
ADMIN_IDS = [841285005]

# Сотрудники будут загружаться из Google Sheets
STAFF_MEMBERS = {}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Сотрудники будут загружаться из Google Sheets
STAFF_MEMBERS = {}
# --- Настройки Google Sheets ---
SERVICE_ACCOUNT_ENV = 'GOOGLE_SERVICE_ACCOUNT_JSON'
SPREADSHEET_NAME = 'Kingsman Rent Orders'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# Глобальные переменные
creds = None
@@ -37,20 +50,37 @@
order_confirmations = {}  # Для хранения подтверждений
staff_management_data = {}  # Для управления сотрудниками


# --- Инициализация Google Sheets ---
def init_google_sheets():
    """Инициализация Google Sheets"""
    """Инициализация Google Sheets через переменные окружения"""
global creds, gc, worksheet_orders, worksheet_assignments, worksheet_staff, sheets_enabled
try:
        # Загружаем service account из переменной окружения
        service_account_file = load_service_account()
        creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        # Получаем данные из переменной окружения
        service_account_json = os.getenv(SERVICE_ACCOUNT_ENV)
        
        if not service_account_json:
            print(f"❌ {SERVICE_ACCOUNT_ENV} не найден в переменных окружения")
            # Попробуем прочитать из файла для локальной разработки
            try:
                with open('service_account.json', 'r') as f:
                    service_account_info = json.load(f)
                print("✅ Загружен service_account.json из файла (для разработки)")
            except FileNotFoundError:
                print("❌ service_account.json также не найден")
                return False
        else:
            # Парсим JSON из переменной окружения
            service_account_info = json.loads(service_account_json)
            print("✅ Service account загружен из переменных окружения")
        
        # Создаем credentials
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
gc = gspread.authorize(creds)

        # Открываем таблицу
        # Остальной код остается без изменений
spreadsheet = gc.open(SPREADSHEET_NAME)

        # Лист заказов
try:
worksheet_orders = spreadsheet.worksheet("Orders")
except gspread.WorksheetNotFound:
@@ -61,7 +91,6 @@ def init_google_sheets():
]
worksheet_orders.append_row(headers)

        # Лист назначений сотрудников
try:
worksheet_assignments = spreadsheet.worksheet("Assignments")
except gspread.WorksheetNotFound:
@@ -72,7 +101,6 @@ def init_google_sheets():
]
worksheet_assignments.append_row(headers)

        # Лист сотрудников
try:
worksheet_staff = spreadsheet.worksheet("Staff")
except gspread.WorksheetNotFound:
@@ -82,7 +110,6 @@ def init_google_sheets():
"Added At", "Added By", "Status"
]
worksheet_staff.append_row(headers)
            # Добавляем главного администратора по умолчанию
worksheet_staff.append_row([
841285005, "Denis_Kingsman", "admin", "Администратор",
datetime.now().strftime("%d.%m.%Y %H:%M"), "system", "active"
@@ -96,6 +123,7 @@ def init_google_sheets():
print(f"❌ Ошибка инициализации Google Sheets: {e}")
return False


# --- Загрузка сотрудников из Google Sheets ---
async def load_staff_from_sheets():
"""Загрузка сотрудников из Google Sheets"""
@@ -471,18 +499,6 @@ def staff_actions_keyboard(order_id) -> InlineKeyboardMarkup:
])


def staff_management_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления сотрудниками"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить сотрудника", callback_data="add_staff"),
            InlineKeyboardButton(text="📋 Список сотрудников", callback_data="list_staff")
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить должность", callback_data="edit_position"),
            InlineKeyboardButton(text="🗑️ Удалить сотрудника", callback_data="remove_staff")
        ]
    ])


# --- Команды бота ---
@@ -545,20 +561,6 @@ async def cmd_status(message: Message):


# --- Команды управления сотрудниками ---
@dp.message(Command("staff"))
async def cmd_staff(message: Message):
    """Управление сотрудниками - главное меню"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Эта команда только для администраторов.")
        return

    await message.answer(
        "👥 Управление сотрудниками\n\n"
        "Выберите действие:",
        reply_markup=staff_management_keyboard()
    )


@dp.message(Command("add_staff"))
async def cmd_add_staff(message: Message):
"""Добавление сотрудника - начало процесса"""
@@ -1152,13 +1154,7 @@ async def cmd_debug_orders(message: Message):

# --- Запуск ---
async def main():
    print("🤖 Запуск бота Kingsman Rent...")
    
    # Проверка переменных окружения
    print("🔧 Проверка переменных окружения:")
    print(f"BOT_TOKEN: {'✅' if os.getenv('BOT_TOKEN') else '❌ (используется значение по умолчанию)'}")
    print(f"GROUP_ID: {'✅' if os.getenv('GROUP_ID') else '❌ (используется значение по умолчанию)'}")
    print(f"SERVICE_ACCOUNT_JSON: {'✅' if os.getenv('SERVICE_ACCOUNT_JSON') else '❌ (будет использоваться файл service_account.json)'}")
    print("🤖 Запуск бота он просыпается уже...")

# Инициализация Google Sheets
if not init_google_sheets():
@@ -1174,7 +1170,7 @@ async def main():
print(f"✅ Подключение установлено. Заказов в таблице: {len(test_orders)}")
print(f"👥 Сотрудников в системе: {len(STAFF_MEMBERS)}")

    print("✅ Бот запущен и готов к работе!")
    print("✅ Бот запущен и готов к работе, проснулся xD")
print("💡 Режим: Прямая работа с Google Sheets")
print("🔧 Доступные команды: /start, /status, /my_orders, /staff")
print("👥 Команды управления сотрудниками:")
@@ -1194,4 +1190,3 @@ async def main():
print("❌ Бот остановлен пользователем")
except Exception as e:
print(f"❌ Критическая ошибка: {e}")
