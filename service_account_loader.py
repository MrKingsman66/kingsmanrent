import os
import json

def load_service_account():
    """Загружает service account из переменной окружения"""
    service_account_json = os.environ.get("SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise ValueError("SERVICE_ACCOUNT_JSON environment variable is not set")
    
    # Парсим JSON и сохраняем во временный файл
    service_account_data = json.loads(service_account_json)
    with open('service_account.json', 'w') as f:
        json.dump(service_account_data, f)
    
    return 'service_account.json'
