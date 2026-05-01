"""
안전한 로깅 유틸리티 브릿지 파일
Windows GUI 환경에서 sys.stderr 접근 시 OSError를 방지하기 위한 로깅 시스템.
이제 shared/logger.py 로직을 공유합니다.
"""
import logging
import os
import sys

# shared 모듈 경로 추가
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.logger import setup_logger as _shared_setup_logger
from shared.logger import get_logger as _shared_get_logger

def setup_logger(name, log_file='lead_sig.log', level=logging.DEBUG):
    """
    로거를 설정합니다. (shared/logger 호환)
    """
    # 콘솔 출력(StreamHandler)은 삭제하여 터미널 창(파워쉘) 로그 발생 방지
    # 로그는 UI 전광판 하단과 lead_sig.log 파일에만 기록됩니다.
    
    # Lead_Sig는 루트 디렉토리에 로그를 바로 남기므로 log_dir="." 로 줌
    return _shared_setup_logger(name=name, log_dir=".", log_file=log_file, console_out=False, level=level)

def get_logger(name):
    """
    로거를 가져옵니다. 없으면 새로 생성합니다. 
    """
    return _shared_get_logger(name, log_dir=".", log_file='lead_sig.log', console_out=False, level=logging.DEBUG)
