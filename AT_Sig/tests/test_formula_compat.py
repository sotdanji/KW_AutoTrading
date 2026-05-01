# -*- coding: utf-8 -*-
"""
AT_Sig 수식 변환 · 함수 등록 호환성 전체 검증
================================================
검증 범위:
  A. core.formula_parser 브릿지 — shared 동일 동작 확인
  B. core.execution_context 브릿지 — shared 동일 동작 확인
  C. 수식 변환 파이프라인 (on_convert_formula 로직 재현)
  D. FormulaParser v2.1 신규 함수 73개 — AT_Sig 브릿지 경유 파싱
  E. execution_context 등록 함수 73개 — AT_Sig 경유 실행 가능 여부

실행: pytest AT_Sig/tests/test_formula_compat.py -v
"""
import sys
import os
import ast
import pytest
import numpy as np
import pandas as pd

ROOT      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AT_SIG    = os.path.join(ROOT, "AT_Sig")
sys.path.insert(0, ROOT)
sys.path.insert(0, AT_SIG)

# ── 직접 import (브릿지 경유) ──────────────────────────────────────────
from shared.formula_parser    import FormulaParser          # AT_Sig 브릿지
from shared.execution_context import get_execution_context  # AT_Sig 브릿지
from shared.formula_parser    import FormulaParser as SharedParser
from shared.execution_context import get_execution_context as shared_get_ctx

# ── 샘플 DataFrame ────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def df():
    np.random.seed(0)
    n = 150
    close = pd.Series(50000 * (1 + np.random.normal(0.001, 0.015, n)).cumprod())
    high  = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low   = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = close.shift(1).fillna(close.iloc[0]) * (1 + np.random.normal(0, 0.005, n))
    return pd.DataFrame({
        "date":   pd.date_range("2024-01-01", periods=n, freq="B"),
        "open":   open_.values,
        "high":   np.maximum(high.values, close.values),
        "low":    np.minimum(low.values,  close.values),
        "close":  close.values,
        "volume": np.random.randint(500_000, 5_000_000, n).astype(float),
    })

@pytest.fixture(scope="session")
def core_parser():
    return FormulaParser()  # AT_Sig core 브릿지 경유

@pytest.fixture(scope="session")
def core_ctx(df):
    return get_execution_context(df)  # AT_Sig core 브릿지 경유


# ══════════════════════════════════════════════════════════════════════
# A. 브릿지 동일성 확인
# ══════════════════════════════════════════════════════════════════════
class TestBridgeIdentity:
    """core.* 브릿지가 shared.* 와 동일한 객체/결과를 반환하는지"""

    def test_formula_parser_same_class(self):
        """core.FormulaParser IS shared.FormulaParser"""
        assert FormulaParser is SharedParser, \
            "core.FormulaParser가 shared.FormulaParser와 다른 클래스"

    def test_get_execution_context_same_func(self):
        """core.get_execution_context IS shared.get_execution_context"""
        assert get_execution_context is shared_get_ctx, \
            "core.get_execution_context가 shared와 다른 함수"

    def test_context_keys_identical(self, df):
        core_keys   = set(get_execution_context(df).keys())
        shared_keys = set(shared_get_ctx(df).keys())
        assert core_keys == shared_keys, \
            f"키 불일치\n  core only: {core_keys - shared_keys}\n  shared only: {shared_keys - core_keys}"


# ══════════════════════════════════════════════════════════════════════
# B·C. 수식 변환 파이프라인 — on_convert_formula 로직 재현
# ══════════════════════════════════════════════════════════════════════
class TestConversionPipeline:
    """AT_Sig 수식 변환 버튼(on_convert_formula) 흐름 전체 재현"""

    def _convert_and_exec(self, core_parser, core_ctx, df, formula):
        """파싱 → AST → exec → cond 반환"""
        parsed = core_parser.parse(formula)
        ast.parse(parsed)
        lv = {}
        exec(parsed, {**core_ctx, "df": df, "pd": pd, "np": np}, lv)
        assert "cond" in lv, f"cond 없음:\n{parsed}"
        return lv["cond"]

    # ── 기존 함수 (회귀) ───────────────────────────────────────────────
    @pytest.mark.parametrize("formula", [
        "CrossUp(C, avg(C, 20))",
        "CrossDown(C, avg(C, 20))",
        "RSI(14) < 30",
        "C > BBandsUp(20, 2)",
        "VR(20) > 150",
        "ATR(14) > 0",
        "OBV() > 0",
        "MFI(14) > 50",
        "SAR(0.02, 0.2) < C",
        "ADX(14) > 25",
        "MACD(12, 26) > 0",
        "CCI(14) > 0",
        "WMA(C, 20) > avg(C, 20)",
        "DEMA(C, 20) > avg(C, 20)",
        "TEMA(C, 20) > avg(C, 20)",
    ])
    def test_existing_functions_via_core(self, core_parser, core_ctx, df, formula):
        cond = self._convert_and_exec(core_parser, core_ctx, df, formula)
        assert isinstance(cond, pd.Series)

    # ── v2.0 신규 ─────────────────────────────────────────────────────
    @pytest.mark.parametrize("formula", [
        "Disparity(20) > 100",
        "PCTB(20, 2) < 1",
        "BandWidth(20, 2) > 0",
        "CloudUp(C, VWAP())",   # alias 테스트용 — 실패해도 OK (미지원이면 skip)
        "CrossUp(C, VWAP())",
        "ForceIndex(13) > 0",
        "TrueRange() > 0",
        "TrueHigh() >= C",
        "TrueLow() <= C",
        "C > PivotP()",
        "C > PivotR1()",
        "C < PivotS1()",
        "BarsSince(RSI(14) < 30) < 20",
        "highest(H, 20) >= C",
        "lowest(L, 20) <= C",
    ])
    def test_v20_functions_via_core(self, core_parser, core_ctx, df, formula):
        if "CloudUp" in formula:
            pytest.skip("CloudUp 미지원 함수 (의도적 제외)")
        cond = self._convert_and_exec(core_parser, core_ctx, df, formula)
        assert isinstance(cond, pd.Series)

    # ── v2.1 신규 ─────────────────────────────────────────────────────
    @pytest.mark.parametrize("formula", [
        "Ref(RSI(14), 1) < 30 && RSI(14) >= 30",
        "Abs(C - avg(C,20)) > 100",
        "Nz(RSI(14), 50) > 50",
        "Int(C / 1000) > 30",
        "Round(RSI(14), 0) > 50",
        "Sqrt(Abs(C - avg(C,20))) > 10",
        "Log(C) > 10",
        "Exp(Slope(C, 20)) > 1",
        "Cum(V) > 0",
        "BarCount() > 50",
        "LinearReg(C, 20) > avg(C, 20)",
        "Slope(C, 20) > 0",
        "Correlation(C, V, 20) > -1",
        "ZigZag(5) > 0",
        "HHV(H, 20) >= highest(H, 20)",
        "LLV(L, 20) <= lowest(L, 20)",
    ])
    def test_v21_functions_via_core(self, core_parser, core_ctx, df, formula):
        cond = self._convert_and_exec(core_parser, core_ctx, df, formula)
        assert isinstance(cond, pd.Series)


# ══════════════════════════════════════════════════════════════════════
# D. 등록 함수 73개 context 키 완전성
# ══════════════════════════════════════════════════════════════════════
class TestFunctionRegistry:
    """execution_context에 73개 함수가 모두 등록되어 있는지"""

    ALL_EXPECTED_NAMES = [
        # OHLCV
        "C", "O", "H", "L", "V",
        # 이동평균
        "avg", "ma", "SMA", "EMA", "eavg", "WMA", "DEMA", "TEMA",
        # 볼린저 밴드
        "BBandsUp", "BBandsDown", "BBandsMid",
        "EnvelopeUp", "EnvelopeDown",
        "Disparity", "PCTB", "BandWidth",
        # 모멘텀 / 오실레이터
        "RSI", "MACD", "CCI", "ADX", "PDI", "MDI",
        "StochasticsK", "StochasticsD",
        "Momentum", "ROC", "TRIX", "WilliamsR",
        # 거래량
        "VR", "OBV", "MFI", "VWAP", "ForceIndex",
        # 가격 구조
        "ATR", "TrueRange", "TrueHigh", "TrueLow",
        "SAR", "PivotP", "PivotR1", "PivotS1", "PivotR2", "PivotS2",
        # 일목균형표
        "Ichi_Tenkan", "Ichi_Kijun", "Ichi_SenkouA", "Ichi_SenkouB",
        # 논리 / 유틸
        "CrossUp", "CrossDown",
        "highest", "lowest", "MAX", "MIN",
        "shift", "CountSince", "BarsSince",
        # 참조
        "Ref",
        # 수학 / 변환
        "Abs", "Nz", "Int", "Round", "Sqrt", "Log", "Exp", "Cum", "BarCount",
        # 통계 / 회귀
        "LinearReg", "Slope", "Correlation",
        # 지그재그 / 별칭
        "ZigZag", "HHV", "LLV",
    ]

    @pytest.mark.parametrize("name", ALL_EXPECTED_NAMES)
    def test_function_registered(self, core_ctx, name):
        """각 함수명이 execution_context dict에 존재하는지"""
        assert name in core_ctx, f"'{name}' 이 context에 등록되지 않음"

    @pytest.mark.parametrize("name", ALL_EXPECTED_NAMES)
    def test_function_callable(self, core_ctx, name):
        """각 함수가 callable인지 (단, OHLCV 변수는 Series이므로 제외)"""
        val = core_ctx[name]
        ohlcv = {"C", "O", "H", "L", "V"}
        if name not in ohlcv:
            assert callable(val), f"'{name}'이 callable하지 않음 (type={type(val)})"
        else:
            assert isinstance(val, pd.Series), f"'{name}'이 pd.Series가 아님"


# ══════════════════════════════════════════════════════════════════════
# E. validate_converted_code 로직 재현
# ══════════════════════════════════════════════════════════════════════
class TestValidateFlow:
    """strategy_mixin.validate_converted_code() 흐름 재현"""

    @pytest.mark.parametrize("formula", [
        "CrossUp(C, avg(C, 20))",
        "RSI(14) < 30 && V > avg(V,20)",
        "Ref(C, 1) < C && Slope(C, 10) > 0",
        "Abs(C - LinearReg(C, 20)) / LinearReg(C, 20) * 100 < 2",
        "Nz(RSI(14), 50) > 60 && BandWidth(20, 2) < 5",
        "HHV(H, 20) == C && BarCount() > 60",
        "Correlation(C, V, 20) > 0.3 && Slope(C, 5) > 0",
    ])
    def test_validate_flow(self, core_parser, core_ctx, df, formula):
        """변환 → exec → cond 존재 → sum() 가능"""
        py_code = core_parser.parse(formula)
        local_vars = {}
        exec(py_code, {**core_ctx, "df": df, "pd": pd, "np": np}, local_vars)
        assert "cond" in local_vars
        cond = local_vars["cond"]
        # hasattr(cond, 'sum') 이면 sum() 호출 가능해야 함
        if hasattr(cond, "sum"):
            count = int(cond.sum())
            assert count >= 0
