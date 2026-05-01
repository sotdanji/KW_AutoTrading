import os
import sys

# 프로젝트 루트를 찾아서 shared를 임포트할 수 있게 함
current_file_path = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# shared 버전을 임포트하여 현재 모듈에 할당 (Redirection)
from shared.db_manager import DBManager as SharedDBManager

class DBManager(SharedDBManager):
    """
    [Legacy Shell] Analyzer_Sig/core/db_manager.py
    모든 요청을 shared.db_manager로 리다이렉션합니다.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print("[Legacy] Analyzer_Sig.core.DBManager redirected to Shared version.")
