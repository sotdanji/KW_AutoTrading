import os
import json
import logging

# Analyzer_Sig Configuration (FORCE REAL MODE)

# API Keys
# 캐치계좌 (조회 전용, 매매 불가 - Analyzer_Sig는 데이터 조회만 수행)
REAL_APP_KEY = "o22GbKaDvkYBCyz6FZ73kjFUKk_kauXEfbh75fi0SVU"
REAL_APP_SECRET = "yuDBen6_76SR2JAgv7I52C28vf0IGuhNoDkAq2pzSn8"
REAL_HOST_URL = "https://api.kiwoom.com"
REAL_SOCKET_URL = "wss://api.kiwoom.com:10000"

def get_settings_path():
	"""Returns the absolute path to settings.json"""
	current_dir = os.path.dirname(os.path.abspath(__file__))
	project_root = os.path.dirname(current_dir)
	return os.path.join(project_root, 'settings.json')

def load_settings():
	"""Loads all settings from settings.json, creates default if missing"""
	try:
		path = get_settings_path()
		if not os.path.exists(path):
			default_settings = {
				"account_mode": "REAL",
				"min_price": 1000,
				"min_vol": 50000,
				"initial_deposit": 10000000,
				"position_ratio": 10.0,
				"stop_loss": 3.0,
				"trigger_profit": 5.0,
				"formula_input": "",
				"formula_preview": ""
			}
			with open(path, 'w', encoding='utf-8') as f:
				json.dump(default_settings, f, indent=4, ensure_ascii=False)
			return default_settings
		
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
	"""Returns the API configuration. Analyzer_Sig always uses REAL API."""
	return {
		'app_key': REAL_APP_KEY,
		'app_secret': REAL_APP_SECRET,
		'host_url': REAL_HOST_URL,
		'socket_url': REAL_SOCKET_URL
	}
