# -*- coding: utf-8 -*-
"""
[리팩토링] Releases/BackTester_Release/core/execution_context.py
→ shared/execution_context.py 를 직접 참조합니다.
수정 시 shared/execution_context.py 만 수정하세요.
"""
from shared.execution_context import get_execution_context  # noqa: F401
__all__ = ['get_execution_context']
