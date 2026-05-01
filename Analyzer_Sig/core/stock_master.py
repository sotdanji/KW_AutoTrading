import os
import sys

current_file_path = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_file_path))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# shared 모듈의 내용들을 현재 모듈로 가져옴 (Proxy)
from shared.stock_master import *
print("[Legacy] Analyzer_Sig.core.stock_master redirected to Shared version.")
