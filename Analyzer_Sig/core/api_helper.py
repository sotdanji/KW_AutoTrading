"""
[브릿지 모듈] core/api_helper.py
이 파일은 하위 호환성을 위해 유지되는 얇은 래퍼입니다.
실제 구현은 shared/api.py에 있습니다.
"""
import sys
import os

# sys.path에 프로젝트 루트 추가 (shared 모듈 접근)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from config import REAL_CONFIG, MOCK_CONFIG
from shared.api import get_token, fetch_data, get_kw_token as _shared_get_kw_token, fetch_kw_data
from core.logger import get_logger

logger = get_logger(__name__)


def get_config(mode: str = "PAPER") -> dict:
	"""모드에 따른 API 설정 반환"""
	if mode == "REAL":
		return REAL_CONFIG
	return MOCK_CONFIG


def get_kw_token(mode: str = "PAPER") -> str | None:
	"""
	config.py의 키를 사용하여 키움 REST API 토큰 발급.
	shared/api.get_kw_token에 키를 주입하여 위임.
	"""
	cfg = get_config(mode)
	return get_token(cfg['host_url'], cfg['app_key'], cfg['app_secret'])


# fetch_kw_data는 shared/api.py에서 직접 재사용 (시그니처 동일)
# from shared.api import fetch_kw_data  <- 위에서 이미 import 됨
