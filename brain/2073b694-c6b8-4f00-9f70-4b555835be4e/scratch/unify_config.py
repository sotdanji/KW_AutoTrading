import os
import re

# [안실장 유지보수 스크립트] 계좌 모드 변수명 및 값 통일화
# 대상: AT_Sig, Analyzer_Sig, Lead_Sig, BackTester, shared
# 규칙:
# 1. JSON 키: "account_mode"
# 2. 전역 상수: ACCOUNT_MODE
# 3. 값: "REAL" / "PAPER"

TARGET_DIRS = ["AT_Sig", "Analyzer_Sig", "Lead_Sig", "BackTester", "shared"]
PROJECT_ROOT = r"d:\AG\KW_AutoTrading"

# 1. 문자열 교체 맵 (기존 -> 신규)
VALUE_MAP = {
	'"Mock"': '"PAPER"',
	"'Mock'": "'PAPER'",
	'"Real"': '"REAL"',
	"'Real'": "'REAL'",
	'"실전"': '"REAL"',
	"'실전'": "'REAL'",
	'"모의"': '"PAPER"',
	"'모의'": "'PAPER'",
}

# 2. 변수명 교체 맵
VAR_MAP = {
	'process_name': 'account_mode',
	'DATA_MODE': 'ACCOUNT_MODE',
	'account_type': 'account_mode'
}

def process_file(filepath):
	try:
		with open(filepath, 'r', encoding='utf-8') as f:
			content = f.read()
		
		original = content
		
		# 변수명 교체 (단어 경계 확인)
		for old_var, new_var in VAR_MAP.items():
			# SQL의 REAL 타입은 건드리지 않도록 정규식 사용
			if old_var == 'DATA_MODE' or old_var == 'ACCOUNT_MODE':
				content = re.sub(rf'\b{old_var}\b', new_var, content)
			else:
				# process_name, account_type 등은 따옴표 안에서도 바뀔 수 있음 (JSON 키)
				content = re.sub(rf'\b{old_var}\b', new_var, content)

		# 값 교체
		for old_val, new_val in VALUE_MAP.items():
			content = content.replace(old_val, new_val)
		
		if content != original:
			with open(filepath, 'w', encoding='utf-8') as f:
				f.write(content)
			print(f"Updated: {filepath}")
			
	except Exception as e:
		print(f"Error processing {filepath}: {e}")

def run_unification():
	for root_dir in TARGET_DIRS:
		full_path = os.path.join(PROJECT_ROOT, root_dir)
		if not os.path.exists(full_path):
			continue
			
		for root, dirs, files in os.walk(full_path):
			# Backup 폴더 제외
			if 'Backups' in root or 'Releases' in root:
				continue
				
			for file in files:
				if file.endswith(('.py', '.json')):
					process_file(os.path.join(root, file))

if __name__ == "__main__":
	run_unification()
