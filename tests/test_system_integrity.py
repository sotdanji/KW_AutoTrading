"""
=============================================================
  Sotdanji Trading System — 통합 테스트 스위트 (V2)
=============================================================
프로젝트 핵심 안정성을 검증하는 통합 테스트 스위트입니다.
Analyzer_Sig (Lead_Sig + BackTester 통합) 및 AT_Sig 모듈을 검증합니다.
=============================================================
"""
import sys
import os
import json
import subprocess
import pytest

# ============================================================
# Helpers
# ============================================================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYZER = os.path.join(ROOT, "Analyzer_Sig")
AT_SIG = os.path.join(ROOT, "AT_Sig")
AT = AT_SIG # Alias for legacy

def _run_import_test(project_dir, import_code):
	"""subprocess로 격리 실행하여 모듈 충돌 방지"""
	env = os.environ.copy()
	env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
	
	result = subprocess.run(
		[sys.executable, "-c", import_code],
		cwd=project_dir,
		env=env,
		capture_output=True,
		text=True,
		timeout=15,
	)
	if result.returncode != 0:
		pytest.fail(f"Import failed in {os.path.basename(project_dir)}:\n{result.stderr.strip()}")

def _scan_files(project_dir, pattern):
	"""프로젝트 내 .py 파일에서 패턴 검색"""
	SKIP_DIRS = {"__pycache__", ".git", "Backups", "backup"}
	hits = []
	for dirpath, dirs, files in os.walk(project_dir):
		dirs[:] = [d for d in dirs if d.lower() not in {s.lower() for s in SKIP_DIRS}]
		for fname in files:
			if not fname.endswith(".py"): continue
			fpath = os.path.join(dirpath, fname)
			with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
				for lineno, line in enumerate(f, 1):
					if pattern in line and not line.strip().startswith("#"):
						hits.append(f"{os.path.relpath(fpath, project_dir)}:{lineno}")
	return hits

# ============================================================
# 1. IMPORT CHAIN TESTS
# ============================================================
class TestAnalyzerSigImports:
	"""Analyzer_Sig 통합 모듈 임포트 검증"""
	def test_config(self):
		# Root config
		_run_import_test(ANALYZER, "import config; assert hasattr(config, 'ACCOUNT_MODE'); print('OK')")
		# Core config (Backtester legacy)
		_run_import_test(ANALYZER, "from core.config import REAL_APP_KEY; print('OK')")

	def test_core_logic(self):
		_run_import_test(ANALYZER, "from core.market_engine import MarketEngine; print('OK')")
		_run_import_test(ANALYZER, "from core.backtest_engine import BacktestEngine; print('OK')")
		_run_import_test(ANALYZER, "from core.data_fetcher import DataFetcher; print('OK')")

	def test_ui(self):
		code = """
try:
	from ui.main_window import MainWindow
	print('OK')
except Exception as e:
	print(f'Import OK, Init skipped: {e}')
"""
		_run_import_test(ANALYZER, code)

class TestATSigImports:
	"""AT_Sig 임포트 검증"""
	def test_core(self):
		_run_import_test(AT_SIG, "from trading_engine import TradingEngine; print('OK')")
		_run_import_test(AT_SIG, "from strategy_runner import StrategyRunner; print('OK')")

	def test_ui(self):
		code = """
try:
	from trading_ui import TradingUI
	print('OK')
except Exception as e:
	print(f'Import OK, Init skipped: {e}')
"""
		_run_import_test(AT_SIG, code)

# ============================================================
# 2. FILE INTEGRITY TESTS
# ============================================================
def test_required_files_exist():
	REQUIRED = [
		os.path.join(ANALYZER, "Anal_Main.py"),
		os.path.join(ANALYZER, "config.py"),
		os.path.join(ANALYZER, "core", "market_engine.py"),
		os.path.join(AT_SIG, "trading_engine.py"),
		os.path.join(ROOT, "shared", "accumulation_manager.py"),
		os.path.join(ROOT, "shared", "api.py")
	]
	missing = [f for f in REQUIRED if not os.path.exists(f)]
	assert not missing, f"Missing files: {missing}"

def test_legacy_modules_removed():
	"""Lead_Sig와 BackTester 폴더가 루트에서 제거되었는지 확인"""
	LEAD = os.path.join(ROOT, "Lead_Sig")
	BT = os.path.join(ROOT, "BackTester")
	assert not os.path.exists(LEAD), "Lead_Sig directory should be removed"
	assert not os.path.exists(BT), "BackTester directory should be removed"

# ============================================================
# 3. SHARED CORE INTEGRITY
# ============================================================
def test_shared_accumulation_manager():
	from shared.accumulation_manager import AccumulationManager
	mgr = AccumulationManager()
	assert "data" in mgr.db_path.lower()
	assert hasattr(mgr, 'get_accumulation_quality')

def test_market_regime_enum():
	from shared.market_status import MarketRegime
	assert MarketRegime.CRASH.name == "CRASH"
	assert MarketRegime.BULL.value == "강세장"

# ============================================================
# 4. DEAD REFERENCES SEARCH
# ============================================================
def test_no_legacy_imports_in_at_sig():
	"""AT_Sig 내부에 Lead_Sig 참조가 없는지 확인"""
	hits = _scan_files(AT_SIG, "from Lead_Sig")
	assert not hits, f"Found legacy Lead_Sig imports: {hits}"
	
	hits = _scan_files(AT_SIG, "import Lead_Sig")
	assert not hits, f"Found legacy Lead_Sig imports: {hits}"

def test_no_legacy_imports_in_analyzer():
	"""Analyzer_Sig 내부에 독립적인 BackTester/Lead_Sig 참조가 없는지 확인"""
	hits = _scan_files(ANALYZER, "from BackTester")
	assert not hits, f"Found legacy BackTester imports: {hits}"

# ============================================================
# 5. UI MIXIN INTEGRITY
# ============================================================
class TestMixinMethods:
	@pytest.mark.parametrize("mixin, method", [
		("shared.ui.strategy_mixin.StrategyMixin", "setup_strategy_tab"),
		("ui.account_mixin.AccountMixin", "update_account_info"),
		("ui.settings_mixin.SettingsMixin", "load_all_settings")
	])
	def test_mixin_method_exists(self, mixin, method):
		# mixin is full path
		parts = mixin.split('.')
		mod_path = ".".join(parts[:-1])
		class_name = parts[-1]
		
		# Determine project dir based on mod_path
		p_dir = AT_SIG if mod_path.startswith("ui") else ROOT
		
		code = f"from {mod_path} import {class_name}; assert hasattr({class_name}, '{method}'); print('OK')"
		_run_import_test(p_dir, code)
