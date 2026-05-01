import logging
import os
import sys

# shared 모듈 경로 추가
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.logger import setup_logger as _shared_setup_logger
from shared.logger import get_logger as _shared_get_logger

# 로그 레벨 설정
LOG_LEVEL = logging.DEBUG

def setup_logger(name=__name__, log_dir="logs", log_file="application.log"):
    """
    AT_Sig 전용 로거 설정 (shared/logger를 사용하여 통일)
    """
    return _shared_setup_logger(name=name, log_dir=log_dir, log_file=log_file, console_out=True, level=LOG_LEVEL)

def get_logger(name):
    # Backward compatibility if needed
    return _shared_get_logger(name, log_dir="logs", log_file="application.log", console_out=True, level=LOG_LEVEL)

# 기본 로거 인스턴스 (모듈 레벨에서 사용 가능)
log = setup_logger("AT_Sig")
