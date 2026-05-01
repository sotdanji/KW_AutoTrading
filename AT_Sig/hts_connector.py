import sys
import os

# ROOT 경로 추가 (shared 패키지 참조용)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
	from shared.hts_connector import is_admin, send_to_hts, find_hts_window, find_0600_chart_window
except ImportError:
	# 만약 shared를 찾지 못하는 환경이라면 기존 로직 백업 (거의 발생하지 않음)
	from .hts_connector_legacy import is_admin, send_to_hts
