# -*- coding: utf-8 -*-
import re

class HangulVariableConverter:
    """
    한글 변수명을 파이썬에서 실행 가능한 영문 변수명으로 변환하는 클래스.
    
    예: '단기이평 = MA(C, 5)' -> '_KVAR_0 = MA(C, 5)'
    """
    
    def __init__(self):
        self.var_map = {}
        self.counter = 0
        # 매칭된 한글 변수 패턴 (한글, 숫자, 밑줄 허용, 숫자로 시작 불가)
        self.korean_var_pattern = re.compile(r'[가-힣][가-힣0-9_]*')

    def convert(self, code: str) -> str:
        """
        코드 내의 한글 변수를 안전한 영문 변수명(_KVAR_n)으로 변환합니다.
        """
        self.var_map = {}
        self.counter = 0

        def replace_match(match):
            korean_var = match.group(0)
            if korean_var not in self.var_map:
                safe_name = f"_KVAR_{self.counter}"
                self.var_map[korean_var] = safe_name
                self.counter += 1
            return self.var_map[korean_var]

        # 정규식을 사용하여 한글 변수 치환
        converted_code = self.korean_var_pattern.sub(replace_match, code)
        return converted_code

    def restore(self, code: str) -> str:
        """
        (디버깅용) 변환된 코드를 다시 한글 변수명으로 복원합니다.
        """
        restored_code = code
        # 긴 변수명부터 치환하여 부분 일치 오류 방지 (필요 시)
        for k_var, e_var in self.var_map.items():
            restored_code = restored_code.replace(e_var, k_var)
        return restored_code

    def get_mapping(self) -> dict:
        """변환 매핑 테이블 반환"""
        return self.var_map
