import os

# Чувствительные данные будут подставляться при деплое
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", -1002773883024))
TOPIC_ORDERS = int(os.environ.get("TOPIC_ORDERS", 81003))
TOPIC_SUPPORT = int(os.environ.get("TOPIC_SUPPORT", 81451))
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "841285005").split(",")]

# Настройки Google Sheets
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
SPREADSHEET_NAME = 'Kingsman Rent Orders'
