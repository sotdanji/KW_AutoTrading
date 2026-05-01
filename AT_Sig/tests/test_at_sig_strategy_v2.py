# -*- coding: utf-8 -*-
"""
AT_Sig 전략 검증 pytest
=========================
검증 범위:
  A. AT_Sig/strategies/ JSON 전략 파일 — formula 파싱 + python_code exec
  B. strategy_runner.analyze_data() 엔드투엔드 실행
  C. execution_context 브릿지 (core → shared) 일관성
  D. BackTester 수정 사항과의 호환성 확인

실행: pytest AT_Sig/tests/test_at_sig_strategy_v2.py -v
"""
import sys
import os
import ast
import json
import pytest
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from shared.formula_parser import FormulaParser
from shared.execution_context import get_execution_context as shared_get_ctx

AT_SIG_DIR    = os.path.join(ROOT, "AT_Sig")
STRATEGY_DIR  = os.path.join(ROOT, "shared", "strategies")

sys.path.insert(0, AT_SIG_DIR)

# ── 공용 샘플 DataFrame ────────────────────────────────────────────────
@pytest.fixture(scope="session")
def sample_df():
    np.random.seed(42)
    n = 150
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = np.random.normal(0.001, 0.015, n)
    close = pd.Series(50000 * (1 + returns).cumprod(), dtype=float)
    high  = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low   = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = close.shift(1).fillna(close.iloc[0]) * (1 + np.random.normal(0, 0.005, n))
    volume = pd.Series(np.random.randint(500_000, 5_000_000, n).astype(float))
    df = pd.DataFrame({
        "date":   dates,
        "open":   open_.values,
        "high":   high.values,
        "low":    low.values,
        "close":  close.values,
        "volume": volume.values,
    })
    df["high"] = df[["high", "close"]].max(axis=1)
    df["low"]  = df[["low",  "close"]].min(axis=1)
    return df

@pytest.fixture(scope="session")
def parser():
    return FormulaParser()

@pytest.fixture(scope="session")
def ctx(sample_df):
    return shared_get_ctx(sample_df)


# ── 전략 JSON 로더 ─────────────────────────────────────────────────────
def _load_at_sig_strategies():
    strategies = []
    if not os.path.isdir(STRATEGY_DIR):
        return strategies
    for fname in sorted(os.listdir(STRATEGY_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(STRATEGY_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        strategies.append((
            data.get("name", fname),
            data.get("formula", ""),
            data.get("python_code", ""),
        ))
    return strategies


# ══════════════════════════════════════════════════════════════════════
# A. 전략 파일 — formula 파싱 + AST 검증
# ══════════════════════════════════════════════════════════════════════
class TestStrategyFormulaParsing:
    """AT_Sig 전략 formula → Python 코드 변환 검증"""

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_formula_parse(self, parser, name, formula, pycode):
        """formula 파싱 성공 여부"""
        if not formula.strip():
            pytest.skip(f"{name}: formula 없음")
        result = parser.parse(formula)
        assert result is not None and len(result) > 0, f"{name}: 빈 파싱 결과"

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_formula_ast(self, parser, name, formula, pycode):
        """파싱된 코드의 AST 문법 확인"""
        if not formula.strip():
            pytest.skip(f"{name}: formula 없음")
        result = parser.parse(formula)
        try:
            ast.parse(result)
        except SyntaxError as e:
            pytest.fail(f"{name} SyntaxError: {e}\n파싱 결과:\n{result}")

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_formula_exec(self, parser, ctx, sample_df, name, formula, pycode):
        """파싱된 코드 exec 실행 → cond 생성 확인"""
        if not formula.strip():
            pytest.skip(f"{name}: formula 없음")
        code = parser.parse(formula)
        lv = {}
        try:
            exec(code, {**ctx, "df": sample_df, "pd": pd, "np": np}, lv)
        except Exception as e:
            pytest.fail(f"{name} exec 오류: {e}\n코드:\n{code}")
        assert "cond" in lv, f"{name}: cond 변수가 생성되지 않음\n코드:\n{code}"
        cond = lv["cond"]
        assert isinstance(cond, pd.Series), f"{name}: cond가 pd.Series가 아님"


# ══════════════════════════════════════════════════════════════════════
# B. 전략 파일 — 기존 python_code 직접 exec
# ══════════════════════════════════════════════════════════════════════
class TestStrategyPythonCode:
    """AT_Sig 전략 JSON의 python_code 직접 실행 검증 (AT_Sig 실제 사용 경로)"""

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_python_code_exec(self, ctx, sample_df, name, formula, pycode):
        """python_code exec 실행 → 오류 없음 확인"""
        if not pycode.strip():
            pytest.skip(f"{name}: python_code 없음")
        try:
            lv = {}
            exec(pycode, {**ctx, "df": sample_df, "pd": pd, "np": np}, lv)
        except Exception as e:
            pytest.fail(f"{name} python_code exec 오류: {e}")

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_python_code_returns_series(self, ctx, sample_df, name, formula, pycode):
        """python_code 실행 후 cond가 pd.Series 타입인지 확인"""
        if not pycode.strip():
            pytest.skip(f"{name}: python_code 없음")
        lv = {}
        try:
            exec(pycode, {**ctx, "df": sample_df, "pd": pd, "np": np}, lv)
        except Exception as e:
            pytest.skip(f"{name}: exec 실패 ({e})")
        if "cond" in lv:
            assert isinstance(lv["cond"], (pd.Series, np.ndarray)), \
                f"{name}: cond 타입 오류 ({type(lv['cond'])})"


# ══════════════════════════════════════════════════════════════════════
# C. execution_context 브릿지 일관성
# ══════════════════════════════════════════════════════════════════════
class TestExecutionContextBridge:
    """core/execution_context → shared/execution_context 브릿지 일관성"""

    def test_get_execution_context_returns_dict(self, sample_df):
        """shared get_execution_context가 dict를 반환하는지"""
        ctx = shared_get_ctx(sample_df)
        assert isinstance(ctx, dict), "get_execution_context가 dict를 반환하지 않음"

    def test_context_has_required_keys(self, sample_df):
        """실행 컨텍스트에 필수 키 포함 여부"""
        ctx = shared_get_ctx(sample_df)
        required = [
            # 기본 OHLCV
            "C", "O", "H", "L", "V",
            # 기존 기술지표
            "_highest", "_lowest", "_MAX", "_MIN",
            "_CrossUp", "_CrossDown", "_CountSince",
            "_EnvelopeUp", "_EnvelopeDown",
            # v2.0 신규
            "_VWAP", "_Disparity", "_PCTB", "_BandWidth",
            "_TrueHigh", "_TrueLow", "_TrueRange",
            "_BarsSince",
            # v2.1 신규
            "_Ref", "_Abs", "_Nz", "_Sqrt", "_Log", "_Exp",
            "_Cum", "_BarCount",
            "_LinearReg", "_Slope_fn", "_Correlation",
            "_ZigZag", "_HHV", "_LLV",
        ]
        missing = [k for k in required if k not in ctx]
        assert not missing, f"컨텍스트에 누락된 키: {missing}"


# ══════════════════════════════════════════════════════════════════════
# D. strategy_runner.analyze_data 엔드투엔드
# ══════════════════════════════════════════════════════════════════════
class TestStrategyRunnerEndToEnd:
    """StrategyRunner.analyze_data() 전체 파이프라인 검증"""

    @pytest.fixture(scope="class")
    def chart_data(self, sample_df):
        """sample_df → chart_data 리스트 변환 (AT_Sig 입력 포맷)"""
        records = []
        for _, row in sample_df.iterrows():
            records.append({
                "stck_bsop_date": row["date"].strftime("%Y%m%d"),
                "stck_oprc":      str(int(row["open"])),
                "stck_hgpr":      str(int(row["high"])),
                "stck_lwpr":      str(int(row["low"])),
                "stck_clpr":      str(int(row["close"])),
                "acml_vol":       str(int(row["volume"])),
            })
        return records

    @pytest.mark.parametrize("name,formula,pycode", _load_at_sig_strategies())
    def test_analyze_data_with_python_code(self, chart_data, name, formula, pycode):
        """StrategyRunner.analyze_data()가 python_code로 오류 없이 실행되는지"""
        if not pycode.strip():
            pytest.skip(f"{name}: python_code 없음")
        try:
            from strategy_runner import StrategyRunner
        except ImportError:
            pytest.skip("strategy_runner 임포트 실패 (AT_Sig 의존성 없음)")

        result = StrategyRunner.analyze_data(chart_data, "005930", pycode)
        assert isinstance(result, dict), "analyze_data가 dict를 반환하지 않음"
        assert "result" in result, "결과 dict에 'result' 키 없음"
        assert isinstance(result["result"], bool), "'result' 값이 bool이 아님"

    def test_analyze_data_no_code_fallback(self, chart_data):
        """strategy_code 없을 때 legacy fallback이 동작하는지"""
        try:
            from strategy_runner import StrategyRunner
        except ImportError:
            pytest.skip("strategy_runner 임포트 실패")

        result = StrategyRunner.analyze_data(chart_data, "005930", strategy_code=None)
        assert isinstance(result, dict)
        assert "result" in result
