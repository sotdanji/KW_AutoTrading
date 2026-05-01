import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_AT_SIG_DIR = os.path.dirname(_TEST_DIR)
_PROJECT_ROOT = os.path.dirname(_AT_SIG_DIR)

if _AT_SIG_DIR not in sys.path:
    sys.path.insert(0, _AT_SIG_DIR)
    
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
