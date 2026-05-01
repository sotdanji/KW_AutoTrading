import os
import json
import logging

# API Keys (Hardcoded as in AT_Sig reference)
PAPER_APP_KEY = "1lJCcuRtHzMxoiB-AhxTNsKpnU-GX5-xofyrcicZWhc"
PAPER_APP_SECRET = "C2GOS7HDXJxLa9ilxdvWKYDAYBFjFYSl4kBXjFMoWXY"
PAPER_HOST_URL = "https://mockapi.kiwoom.com"

REAL_APP_KEY = "UbpgIJ3OWXX61ORy5CzYXKatorz-Uy3UaJOiUNVMIhg"
REAL_APP_SECRET = "V066VVNhWT5EsNzhYMjU8wuBetXxbP8E3Kh1rhuZEfI"
REAL_HOST_URL = "https://api.kiwoom.com"

def get_settings_path():
    """Returns the absolute path to settings.json"""
    # Assuming settings.json is in the root of BackTester (parent of core)
    # core/config.py -> core -> BackTester
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    return os.path.join(project_root, 'settings.json')

def load_settings():
    """Loads all settings from settings.json, creates default if missing"""
    try:
        path = get_settings_path()
        
        # If settings.json doesn't exist, create from template
        if not os.path.exists(path):
            print(f"[INFO] settings.json not found. Creating default settings...")
            
            # Default settings - REAL account for unlimited stock access
            default_settings = {
                "account_type": "REAL",
                "min_price": 1000,
                "min_vol": 50000,
                "initial_deposit": 10000000,
                "position_ratio": 10.0,
                "stop_loss": 3.0,
                "trigger_profit": 5.0,
                "formula_input": "",
                "formula_preview": ""
            }
            
            # Create settings file
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(default_settings, f, indent=4, ensure_ascii=False)
            
            print(f"[INFO] Created default settings.json at: {path}")
            return default_settings
        
        # Load existing settings
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except Exception as e:
        print(f"Error loading settings: {e}")
        return {}

def get_setting(key, default=None):
    """Gets a specific setting value"""
    settings = load_settings()
    return settings.get(key, default)

def get_api_config():
    """Returns the API configuration based on the 'account_type' setting."""
    account_type = get_setting('account_type', 'REAL')  # Default to REAL for backtesting
    
    if account_type == 'REAL':
        return {
            'app_key': REAL_APP_KEY,
            'app_secret': REAL_APP_SECRET,
            'host_url': REAL_HOST_URL
        }
    else:
        return {
            'app_key': PAPER_APP_KEY,
            'app_secret': PAPER_APP_SECRET,
            'host_url': PAPER_HOST_URL
        }
