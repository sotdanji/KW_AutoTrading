import os
import json

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../settings.json")

def get_kw_setting(key, default=''):
    try:
        if not os.path.exists(SETTINGS_FILE):
            return default
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return settings.get(key, default)
    except:
        return default

def update_kw_setting(key, value):
    try:
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        settings[key] = value
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False
