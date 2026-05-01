import os
import time
import json

def get_setting(key, default=''):
	try:
		script_dir = os.path.dirname(os.path.abspath(__file__))
		settings_path = os.path.join(script_dir, 'settings.json')
		
		# 파일 읽기 재시도 로직 (파일 경합 방지)
		for _ in range(3):
			try:
				with open(settings_path, 'r', encoding='utf-8') as f:
					content = f.read().strip()
					if not content:
						# 파일이 비어있으면 잠시 대기 후 재시도
						time.sleep(0.1)
						continue
					settings = json.loads(content)
				return settings.get(key, default)
			except (json.JSONDecodeError, IOError):
				time.sleep(0.1)
				
		# 3회 시도 후에도 실패하면 기본값 반환
		print(f"설정 파일 읽기 실패 (재시도 초과): {key}")
		return default
		
	except Exception as e:
		print(f"오류 발생(get_setting): {e}")
		return default

# 10초 이내 재요청사항 처리
def cached_setting(key, default=''):
	# 여러 key 값의 캐시 관리 (value, read_time) 형태로 저장
	if not hasattr(cached_setting, "_cache"):
		cached_setting._cache = {}

	now = time.time()
	cache = cached_setting._cache

	value_info = cache.get(key, (None, 0))
	cached_value, last_read_time = value_info

	if now - last_read_time > 10 or cached_value is None:
		# 10초 경과하거나 캐시 없음 → 새로 읽음
		cached_value = get_setting(key, default)
		cache[key] = (cached_value, now)
	return cached_value

def update_setting(key, value):
	"""settings.json 파일의 특정 키 값을 업데이트합니다."""
	try:
		script_dir = os.path.dirname(os.path.abspath(__file__))
		settings_path = os.path.join(script_dir, 'settings.json')
		
		with open(settings_path, 'r', encoding='utf-8') as f:
			settings = json.load(f)
		
		settings[key] = value
		
		with open(settings_path, 'w', encoding='utf-8') as f:
			json.dump(settings, f, ensure_ascii=False, indent=2)
		
		# 캐시 무효화
		if hasattr(cached_setting, "_cache"):
			cached_setting._cache = {}
		
		return True
	except Exception as e:
		print(f"설정 업데이트 실패: {e}")
		return False

def get_all_settings():
	"""모든 설정을 dict로 반환합니다."""
	try:
		script_dir = os.path.dirname(os.path.abspath(__file__))
		settings_path = os.path.join(script_dir, 'settings.json')
		
		with open(settings_path, 'r', encoding='utf-8') as f:
			return json.load(f)
	except Exception as e:
		print(f"설정 로드 실패: {e}")
		return {}
