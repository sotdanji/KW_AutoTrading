import re
import pandas as pd
import numpy as np
from .indicators import TechnicalIndicators as TI

class FormulaParser:
    """
    Parses Kiwoom-style signal formulas and converts them into Python/Pandas code.
    Assumes 'df' is the DataFrame with standardized columns (open, high, low, close, volume).
    
    지원 함수:
    - avg(source, period), ma(period) - 이동평균
    - eavg(source, period) - 지수이동평균
    - BBandsUp(period, std), BBandsDown(period, std) - 볼린저 밴드
    - ATR(period) - Average True Range
    - CrossUp(a, b), CrossDown(a, b) - 교차
    - ValueWhen(n, condition, value) - 조건이 참일 때의 값
    - C(n), O(n), H(n), L(n), V(n) - n일 전 데이터
    """

    def __init__(self):
        self.valuewhen_counter = 0
        self.temp_vars = {}
        # Mapping to store original Korean var names if needed for debugging
        self.korean_var_map = {}

    def _get_arg(self, args, index, default=""):
        """Safely get argument from args list, returning default if out of range or empty."""
        if index < len(args) and args[index].strip():
            return args[index].strip()
        return str(default)

    def parse(self, formula):
        """
        Main entry point to convert formula string to Python code.
        Returns a string of Python code that results in a boolean Series 'cond'.
        """
        # Reset state
        self.valuewhen_counter = 0
        self.temp_vars = {}
        self.korean_var_map = {}
        
        # Pre-process Korean variables
        formula = self._preprocess_korean_vars(formula)
        
        # Normalize formula
        formula = formula.strip()
        
        # Remove comments like // ...
        formula = re.sub(r'//.*', '', formula)
        # Remove comments like /* ... */
        formula = re.sub(r'/\*.*?\*/', '', formula, flags=re.DOTALL)
        
        # Smart Split Logic v2:
        # 1. Split by Semicolons (Explicit Separators)
        # 2. Within each chunk, split by Newlines ONLY if it looks like a new assignment.
        #    Otherwise treat newlines as continuations.
        
        raw_chunks = [c.strip() for c in formula.split(';') if c.strip()]
        statements = []
        
        # Regex to detect "Var =" (assignment start)
        # Matches: Start, Identifier, optional space, =, not =
        assignment_pattern = re.compile(r'^[a-zA-Z_]\w*\s*=(?!=)')
        
        for chunk in raw_chunks:
            # Split chunk by newlines to check for implicit separators
            lines_in_chunk = [line.strip() for line in chunk.split('\n') if line.strip()]
            
            current_buffer = []
            for line in lines_in_chunk:
                # If line is new assignment AND we have content in buffer, flush buffer
                if assignment_pattern.match(line) and current_buffer:
                    statements.append(" ".join(current_buffer))
                    current_buffer = []
                current_buffer.append(line)
            
            if current_buffer:
                statements.append(" ".join(current_buffer))
            
        lines = []
        final_expr = None
        
        for stmt in statements:
            # Check if this is an assignment (contains '=')
            # But exclude comparison operators (>=, <=, ==, !=)
            # Simple check: split by '=' and check if left side is a valid identifier
            parts = stmt.split('=')
            is_assignment = False
            
            if len(parts) >= 2:
                left = parts[0].strip()
                # Check if left is a valid variable name (alphanumeric)
                # and right side doesn't start with '=' (== case)
                if re.match(r'^[a-zA-Z_]\w*$', left) and not parts[1].strip().startswith('='):
                    # Also check it's not a comparison inside like "A >= B" being split
                    # Actually, basic assignment usually has just nothing special on left
                    if not any(op in left for op in ['>', '<', '!', ' ']): 
                         is_assignment = True

            if is_assignment:
                var_name = parts[0].strip()
                # Join the rest back in case there were multiple '=' (unlikely but safe)
                expr = '='.join(parts[1:]).strip()
                
                # Process the expression
                processed = self._process_expression(expr)
                lines.append(f"{var_name} = {processed}")
                
                # Store variable for later reference
                self.temp_vars[var_name] = f"{var_name}"
            else:
                # This is the final condition expression
                final_expr = self._process_expression(stmt)
        
        # Add final condition
        if final_expr:
            lines.append(f"cond = {final_expr}")
        elif statements and not final_expr:
            # If the last statement was an assignment, assume we want to use the last variable?
            # Or if statements exist but no final expr? 
            # Usually the last line is the condition.
            # If the last line was an assignment "A=...", technically no condition.
            # But Kiwoom usually ends with condition.
            # We'll assume the user put the condition at the end.
            pass
        
        return "\n".join(lines)
    
    def _process_expression(self, expr):
        """Process a single expression with all transformations."""
        converted = expr.strip()

        # [안실장 픽스] Python 3 정수 리터럴 문법 오류 방지 (Leading Zeros)
        # 091000 -> 91000, 007 -> 7 등으로 변환 (단, 0.1 등 실수는 유지)
        converted = re.sub(r'\b0+([1-9]\d*)\b(?!\.)', r'\1', converted)
        converted = re.sub(r'\b0+0\b(?!\.)', '0', converted)

        # Step -2: Fix Logic Operators
        # A) Convert '!' to '~' for pandas boolean negation (but preserving '!=')
        converted = re.sub(r'!(?!=)', '~', converted)
        
        # B) Convert '=' to '==' if it's not an assignment
        # In Kiwoom logic parts (RHS), '=' implies Comparison, not Assignment.
        # Python uses '=='.
        # Regex: (?<![<>!=~])=(?![=]) means '=' not preceded by <, >, !, =, or ~ and not followed by =
        converted = re.sub(r'(?<![<>!=~])=(?![=])', '==', converted)
        
        # Step -1.5: Handle Implicit Multiplication: "100 (" -> "100 * ("
        # Python interprets 100(...) as a function call.
        # IMPORTANT: 숫자 뒤에 직접 '(' 오는 경우만 처리. 함수명 끝에 숫자가 있는 경우(PivotR1()) 제외.
        # 부정형 뒤-돌아보기: 앞이 알파벳/밑줄이 아닌 경우에만 적용.
        converted = re.sub(r'(?<![a-zA-Z_])(\d)\s*\(', r'\1 * (', converted)

        
        # Step -1: Pre-process Keywords (or -> ||, and -> &&)
        # We convert valid python logical keywords to Kiwoom-style operators
        # so that _wrap_logical_operators can handle them with correct precedence wrapping.
        converted = re.sub(r'\b(or|OR)\b', ' || ', converted)
        converted = re.sub(r'\b(and|AND)\b', ' && ', converted)
        
        # Step 3: Handle Functions
        # IMPORTANT: Process "Inner" functions (Indicators) BEFORE "Outer" functions (CrossUp)
        
        # Define common defaults to avoid backslashes in f-strings (Python 3.11 compat)
        D_CLOSE = "df['close']"
        D_HIGH = "df['high']"
        D_LOW = "df['low']"
        D_VOL = "df['volume']"
        D_AMT = "df['amount']"

        # 3.1 Indicators
        
        # if(condition, true_val, false_val) -> np.where(condition, true_val, false_val)
        converted = self._replace_function(converted, 'if', 
            lambda args: f"np.where({self._get_arg(args, 0, 'True')}, {self._get_arg(args, 1, '0')}, {self._get_arg(args, 2, '0')})")

        # dayopen() -> df['open'] (if daily) or special handling
        # Since we assume 'df' has correct columns, dayopen is usually just shifted 'open' at day start.
        # Simple mapping for now to match O.
        converted = self._replace_function(converted, 'dayopen', lambda args: "df['open']")

        # CountSince(condition, data) -> _CountSince(condition, data)
        converted = self._replace_function(converted, 'CountSince', 
            lambda args: f"_CountSince({self._get_arg(args, 0, 'True')}, {self._get_arg(args, 1, D_CLOSE)})")

        # Highest(Source, Period) -> _highest(Source, Period)
        def replace_highest(args):
            if len(args) == 1:
                return f"_highest({D_HIGH}, {args[0]})"
            return f"_highest({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'highest', replace_highest)

        # Lowest(Source, Period) -> _lowest(Source, Period)
        def replace_lowest(args):
            if len(args) == 1:
                return f"_lowest({D_LOW}, {args[0]})"
            return f"_lowest({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'lowest', replace_lowest)

        # Shift(Source, Period)
        converted = self._replace_function(converted, 'shift', 
            lambda args: f"(({self._get_arg(args, 0, D_CLOSE)}).shift({self._get_arg(args, 1, '1')}))")
            
        # Min(A, B) -> _MIN(A, B)
        # Handle cases where multiple args might be present or just two
        converted = self._replace_function(converted, 'min', 
            lambda args: f"_MIN({', '.join(args)})")
            
        # Max(A, B) -> _MAX(A, B)
        converted = self._replace_function(converted, 'max', 
            lambda args: f"_MAX({', '.join(args)})")

        # BBandsUp
        converted = self._replace_function(converted, 'BBandsUp', 
            lambda args: f"TI.bbands({D_CLOSE}, {self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '2')})[0]")
            
        # BBandsDown
        converted = self._replace_function(converted, 'BBandsDown', 
            lambda args: f"TI.bbands({D_CLOSE}, {self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '2')})[2]")

        # EAVG (Exponential Moving Average)
        def replace_eavg(args):
            if len(args) == 1:
                return f"_ema({D_CLOSE}, {args[0]})"
            return f"_ema({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'eavg', replace_eavg)
        
        # ATR
        converted = self._replace_function(converted, 'ATR', 
            lambda args: f"TI.atr({D_HIGH}, {D_LOW}, {D_CLOSE}, {self._get_arg(args, 0, '14')})")
            
        # AVG (Simple Moving Average) - Can take (Source, Period)
        def replace_avg(args):
            if len(args) == 1:
                return f"_ma({D_CLOSE}, {args[0]})"
            return f"_ma({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'avg', replace_avg)

        # MA (Simple Moving Average)
        def replace_ma(args):
            if len(args) == 1:
                return f"_ma({D_CLOSE}, {args[0]})"
            else:
                return f"_ma({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'ma', replace_ma)

        # SUM (Rolling Sum) - sum(source, period)
        def replace_sum(args):
            if len(args) == 1:
                return f"_sum({D_CLOSE}, {args[0]})"
            return f"_sum({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'sum', replace_sum)
            
        # STDEV (Standard Deviation) - stdev(source, period)
        def replace_stdev(args):
            if len(args) == 1:
                return f"_stdev({D_CLOSE}, {args[0]})"
            return f"_stdev({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'stdev', replace_stdev)
        
        # EMA (Exponential Moving Average)
        def replace_ema(args):
            if len(args) == 1:
                return f"_ema({D_CLOSE}, {args[0]})"
            return f"_ema({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'ema', replace_ema)
            
        # EnvelopeUp(Period, Percent) -> _EnvelopeUp(Period, Percent)
        converted = self._replace_function(converted, 'EnvelopeUp',
            lambda args: f"_EnvelopeUp({self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '6')})")

        # EnvelopeDown(Period, Percent) -> _EnvelopeDown(Period, Percent)
        converted = self._replace_function(converted, 'EnvelopeDown',
            lambda args: f"_EnvelopeDown({self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '6')})")

        # VR(Period) -> TI.vr(C, O, V, Period)
        # Explicit conversion prevents _process_past_references from mistaking VR(20) for VR.shift(20)
        VR_C = D_CLOSE
        VR_O = "df['open']"
        VR_V = D_VOL
        converted = self._replace_function(converted, 'VR',
            lambda args: f"TI.vr({VR_C}, {VR_O}, {VR_V}, {args[0]})")
        
        # --- NEW INDICATORS MAPPING ---
        # MACD
        converted = self._replace_function(converted, 'MACD',
            lambda args: f"TI.macd({D_CLOSE}, {self._get_arg(args, 0, '12')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '9')})[0]")
        
        # MACD Oscillator
        def replace_macd_osc(args):
            m_call = f"TI.macd({D_CLOSE}, {self._get_arg(args, 0, '12')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '9')})"
            return f"({m_call}[0] - {m_call}[1])"
        converted = self._replace_function(converted, 'MACD_OSC', replace_macd_osc)

        # Stochastics (Slow/Fast logic mapping via standard slow)
        STOCH_H = D_HIGH
        STOCH_L = D_LOW
        STOCH_C = D_CLOSE
        converted = self._replace_function(converted, 'StochasticsK',
            lambda args: f"TI.stochastics_slow({STOCH_H}, {STOCH_L}, {STOCH_C}, {self._get_arg(args, 0, '12')}, {self._get_arg(args, 1, '5')})[0]")
        converted = self._replace_function(converted, 'StochasticsD',
            lambda args: f"TI.stochastics_slow({STOCH_H}, {STOCH_L}, {STOCH_C}, {self._get_arg(args, 0, '12')}, {self._get_arg(args, 1, '5')}, {self._get_arg(args, 2, '5')})[1]")

        # CCI
        CCI_H = D_HIGH
        CCI_L = D_LOW
        CCI_C = D_CLOSE
        converted = self._replace_function(converted, 'CCI',
            lambda args: f"TI.cci({CCI_H}, {CCI_L}, {CCI_C}, {self._get_arg(args, 0, '14')})")

        # RSI
        converted = self._replace_function(converted, 'RSI',
            lambda args: f"TI.rsi({D_CLOSE}, {self._get_arg(args, 0, '14')})")

        # DMI (PDI/MDI) and ADX
        DMI_H = D_HIGH
        DMI_L = D_LOW
        DMI_C = D_CLOSE
        converted = self._replace_function(converted, 'PDI',
            lambda args: f"TI.dmi({DMI_H}, {DMI_L}, {DMI_C}, {self._get_arg(args, 0, '14')})[0]")
        converted = self._replace_function(converted, 'MDI',
            lambda args: f"TI.dmi({DMI_H}, {DMI_L}, {DMI_C}, {self._get_arg(args, 0, '14')})[1]")
        converted = self._replace_function(converted, 'ADX',
            lambda args: f"TI.adx({DMI_H}, {DMI_L}, {DMI_C}, {self._get_arg(args, 0, '14')})")

        # Volume Indicators (OBV, MFI)
        MFI_H = D_HIGH
        MFI_L = D_LOW
        MFI_C = D_CLOSE
        MFI_V = D_VOL
        converted = self._replace_function(converted, 'OBV',
            lambda args: f"TI.obv({D_CLOSE}, {D_VOL})")
        converted = self._replace_function(converted, 'MFI',
            lambda args: f"TI.mfi({MFI_H}, {MFI_L}, {MFI_C}, {MFI_V}, {self._get_arg(args, 0, '14')})")

        # Parabolic SAR
        SAR_H = D_HIGH
        SAR_L = D_LOW
        converted = self._replace_function(converted, 'SAR',
            lambda args: f"TI.sar({D_HIGH}, {D_LOW}, {self._get_arg(args, 0, '0.02')}, {self._get_arg(args, 1, '0.2')})")

        # Oscillators (Momentum, ROC, TRIX, Williams %R)
        converted = self._replace_function(converted, 'Momentum',
            lambda args: f"TI.momentum({D_CLOSE}, {self._get_arg(args, 0, '12')})")
        converted = self._replace_function(converted, 'ROC',
            lambda args: f"TI.roc({D_CLOSE}, {self._get_arg(args, 0, '12')})")
        converted = self._replace_function(converted, 'TRIX',
            lambda args: f"TI.trix({D_CLOSE}, {self._get_arg(args, 0, '12')})")
        converted = self._replace_function(converted, 'WilliamsR',
            lambda args: f"TI.williams_r({D_HIGH}, {D_LOW}, {D_CLOSE}, {self._get_arg(args, 0, '14')})")

        # Ichimoku (일목균형표)
        converted = self._replace_function(converted, 'Ichi_Tenkan',
            lambda args: f"TI.ichimoku({D_HIGH}, {D_LOW}, {self._get_arg(args, 0, '9')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '52')})[0]")
        converted = self._replace_function(converted, 'Ichi_Kijun',
            lambda args: f"TI.ichimoku({D_HIGH}, {D_LOW}, {self._get_arg(args, 0, '9')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '52')})[1]")
        converted = self._replace_function(converted, 'Ichi_SenkouA',
            lambda args: f"TI.ichimoku({D_HIGH}, {D_LOW}, {self._get_arg(args, 0, '9')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '52')})[2]")
        converted = self._replace_function(converted, 'Ichi_SenkouB',
            lambda args: f"TI.ichimoku({D_HIGH}, {D_LOW}, {self._get_arg(args, 0, '9')}, {self._get_arg(args, 1, '26')}, {self._get_arg(args, 2, '52')})[3]")

        # ================================================================
        # [신규] 이평선 확장
        # ================================================================
        # WMA (가중이동평균)
        converted = self._replace_function(converted, 'WMA',
            lambda args: f"TI.wma({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, '20')})")
        # DEMA (이중지수이동평균)
        converted = self._replace_function(converted, 'DEMA',
            lambda args: f"TI.dema({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, '20')})")
        # TEMA (삼중지수이동평균)
        converted = self._replace_function(converted, 'TEMA',
            lambda args: f"TI.tema({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, '20')})")

        # ================================================================
        # [신규] 볼린저 밴드 파생
        # ================================================================
        # BBandsMid (볼린저 중간선)
        converted = self._replace_function(converted, 'BBandsMid',
            lambda args: f"TI.bbands({D_CLOSE}, {self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '2')})[1]")
        # Disparity(period) - 이격도
        converted = self._replace_function(converted, 'Disparity',
            lambda args: f"TI.disparity({D_CLOSE}, {self._get_arg(args, 0, '20')})")
        # PCTB(period, std) - 볼린저 %B
        converted = self._replace_function(converted, 'PCTB',
            lambda args: f"TI.pctb({D_CLOSE}, {self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '2')})")
        # BandWidth(period, std) - 볼린저 밴드폭
        converted = self._replace_function(converted, 'BandWidth',
            lambda args: f"TI.band_width({D_CLOSE}, {self._get_arg(args, 0, '20')}, {self._get_arg(args, 1, '2')})")

        # ================================================================
        # [신규] 거래량 지표
        # ================================================================
        # VWAP() - 거래량가중평균가 (인수 없음)
        converted = self._replace_function(converted, 'VWAP',
            lambda args: f"TI.vwap({D_HIGH}, {D_LOW}, {D_CLOSE}, {D_VOL})")
        # ForceIndex(period) - 포스 인덱스
        converted = self._replace_function(converted, 'ForceIndex',
            lambda args: f"TI.force_index({D_CLOSE}, {D_VOL}, {self._get_arg(args, 0, '13')})")

        # ================================================================
        # [신규] 가격 구조
        # ================================================================
        # TrueHigh(), TrueLow(), TrueRange()
        converted = self._replace_function(converted, 'TrueHigh',
            lambda args: f"TI.true_high({D_HIGH}, {D_CLOSE})")
        converted = self._replace_function(converted, 'TrueLow',
            lambda args: f"TI.true_low({D_LOW}, {D_CLOSE})")
        converted = self._replace_function(converted, 'TrueRange',
            lambda args: f"TI.true_range({D_HIGH}, {D_LOW}, {D_CLOSE})")
        # Pivot 파생 - PivotP(), PivotR1(), PivotS1(), PivotR2(), PivotS2()
        converted = self._replace_function(converted, 'PivotP',
            lambda args: f"TI.pivot({D_HIGH}, {D_LOW}, {D_CLOSE})[0]")
        converted = self._replace_function(converted, 'PivotR1',
            lambda args: f"TI.pivot({D_HIGH}, {D_LOW}, {D_CLOSE})[1]")
        converted = self._replace_function(converted, 'PivotS1',
            lambda args: f"TI.pivot({D_HIGH}, {D_LOW}, {D_CLOSE})[2]")
        converted = self._replace_function(converted, 'PivotR2',
            lambda args: f"TI.pivot({D_HIGH}, {D_LOW}, {D_CLOSE})[3]")
        converted = self._replace_function(converted, 'PivotS2',
            lambda args: f"TI.pivot({D_HIGH}, {D_LOW}, {D_CLOSE})[4]")

        # ================================================================
        # [신규] 유틸
        # ================================================================
        # BarsSince(condition) - 조건 후 경과봉수
        converted = self._replace_function(converted, 'BarsSince',
            lambda args: f"TI.bars_since({self._get_arg(args, 0, 'False')})")

        # ================================================================
        # [신규] 참조 함수
        # ================================================================
        # Ref(source, N) — N봉 전 값 참조. C(N) 방식과 동일한 shift.
        # 우선순위: 다른 함수보다 먼저 처리해야 내부 함수 치환 후 정상 작동.
        def replace_ref(args):
            if len(args) == 1:
                return f"({args[0]}).shift(1)"
            return f"({args[0]}).shift({args[1]})"
        converted = self._replace_function(converted, 'Ref', replace_ref)
        converted = self._replace_function(converted, 'ref', replace_ref)

        # ================================================================
        # [신규] 수학 / 변환 함수
        # ================================================================
        # Abs(x) — 절댓값
        converted = self._replace_function(converted, 'Abs',
            lambda args: f"({self._get_arg(args, 0, D_CLOSE)}).abs()")
        converted = self._replace_function(converted, 'abs',
            lambda args: f"({self._get_arg(args, 0, D_CLOSE)}).abs()")

        # Nz(x) / Nz(x, default) — NaN → 0 또는 default
        converted = self._replace_function(converted, 'Nz',
            lambda args: f"({args[0]}).fillna({args[1] if len(args) > 1 else 0})")
        converted = self._replace_function(converted, 'nz',
            lambda args: f"({args[0]}).fillna({args[1] if len(args) > 1 else 0})")

        # Int(x) — 정수 변환 (소수점 버림)
        converted = self._replace_function(converted, 'Int',
            lambda args: f"np.floor({args[0]}).astype(float)")

        # Round(x, N) — 반올림
        converted = self._replace_function(converted, 'Round',
            lambda args: f"({args[0]}).round({args[1] if len(args) > 1 else 0})")

        # Sqrt(x) — 제곱근
        converted = self._replace_function(converted, 'Sqrt',
            lambda args: f"np.sqrt({args[0]})")

        # Log(x) — 자연로그
        converted = self._replace_function(converted, 'Log',
            lambda args: f"np.log({self._get_arg(args, 0, D_CLOSE)})")

        # Exp(x) — 지수함수 e^x
        converted = self._replace_function(converted, 'Exp',
            lambda args: f"np.exp({self._get_arg(args, 0, D_CLOSE)})")

        # Cum(x) — 누적합 (처음 봉부터 현재까지)
        converted = self._replace_function(converted, 'Cum',
            lambda args: f"({self._get_arg(args, 0, D_CLOSE)}).cumsum()")

        # BarCount — 인수 없는 키워드, 현재 행 번호(1~n) Series
        # _replace_function 로 처리하되 빈 괄호 허용
        converted = self._replace_function(converted, 'BarCount',
            lambda args: f"pd.Series(np.arange(1, len(df)+1, dtype=float), index=df.index)")

        # ================================================================
        # [신규] 통계 / 회귀
        # ================================================================
        # LinearReg(source, N) — N봉 선형회귀값
        converted = self._replace_function(converted, 'LinearReg',
            lambda args: f"TI.linear_reg({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, '20')})")

        # Slope(source, N) — N봉 선형회귀 기울기
        converted = self._replace_function(converted, 'Slope',
            lambda args: f"TI.slope({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, '20')})")

        # Correlation(A, B, N) — N봉 피어슨 상관계수
        converted = self._replace_function(converted, 'Correlation',
            lambda args: f"TI.correlation({self._get_arg(args, 0, D_CLOSE)}, {self._get_arg(args, 1, D_CLOSE)}, {self._get_arg(args, 2, '20')})")

        # ================================================================
        # [신규] 지그재그 / 구버전 별칭
        # ================================================================
        # ZigZag(pct) — pct% 방향 전환 기준 지그재그
        converted = self._replace_function(converted, 'ZigZag',
            lambda args: f"TI.zigzag({D_CLOSE}, {self._get_arg(args, 0, '5')})")

        # HHV(source, N) — 구버전 highest 별칭
        def replace_hhv(args):
            if len(args) <= 1:
                return f"_highest({D_HIGH}, {self._get_arg(args, 0, '20')})"
            return f"_highest({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'HHV', replace_hhv)

        # LLV(source, N) — 구버전 lowest 별칭
        def replace_llv(args):
            if len(args) <= 1:
                return f"_lowest({D_LOW}, {self._get_arg(args, 0, '20')})"
            return f"_lowest({args[0]}, {args[1]})"
        converted = self._replace_function(converted, 'LLV', replace_llv)

        # Step 4: Handle CrossUp / CrossDown / ValueWhen (Outer functions)
        
        # CrossUp(A, B)
        # Logic: (A(1) <= B(1)) & (A > B)
        # Note: A and B are now likely pandas Series expressions
        def replace_crossup(args):
            a = self._get_arg(args, 0)
            b = self._get_arg(args, 1)
            if not a or not b: return "(False)"
            return f"(({a}.shift(1) <= {b}.shift(1)) & ({a} > {b}))"
        converted = self._replace_function(converted, 'CrossUp', replace_crossup)
        
        # CrossDown(A, B)
        # Logic: (A(1) >= B(1)) & (A < B)
        def replace_crossdown(args):
            a = self._get_arg(args, 0)
            b = self._get_arg(args, 1)
            if not a or not b: return "(False)"
            return f"(({a}.shift(1) >= {b}.shift(1)) & ({a} < {b}))"
        converted = self._replace_function(converted, 'CrossDown', replace_crossdown)
        
        # ValueWhen(n, condition, value)
        def replace_valuewhen(args):
            # n is usually 1 in Kiwoom for simple cases
            n = self._get_arg(args, 0, "1")
            cond = self._get_arg(args, 1)
            val = self._get_arg(args, 2)
            if not cond or not val: return "(np.nan)"
            return f"pd.Series(np.where({cond}, {val}, np.nan), index=df.index).ffill()"
        converted = self._replace_function(converted, 'ValueWhen', replace_valuewhen)
        
        # if(cond, true, false)
        def replace_if(args):
            c = self._get_arg(args, 0, "True")
            t = self._get_arg(args, 1, "0")
            f = self._get_arg(args, 2, "0")
            return f"np.where({c}, {t}, {f})"
        converted = self._replace_function(converted, 'if', replace_if)
        
        # Step 0: Handle Logical Operators (|| -> |, && -> &) WITH PARENTHESIS WRAPPING
        # Must happen AFTER functions because functions might contain &&, || inside args?
        # Kiwoom doesn't usually use logic inside args, but safe to process function strings first.
        # But wait, CrossUp replacement logic injects '&'. 
        # If we process Logic later, we might break the '&' injected by CrossUp?
        # NO. CrossUp returns `( ... & ... )`. It is already parenthesized!
        # So our logic wrapper should respect existing parens.
        
        converted = self._wrap_logical_operators(converted)
        
        # Step 1: Base Variable Mapping (C, O, H, L, V)
        # Now map variables in the remaining string
        converted = self._map_vars_in_str(converted)

        # Step 2: Handle "Past Reference" syntax like C(1), O(2)
        # This converts df['close'](1) -> df['close'].shift(1)
        # Because we mapped C -> df['close'] in Step 1.
        # This must be LAST to avoid matching function calls as shifts.
        converted = self._process_past_references(converted)
        
        return converted
    
    def _process_past_references(self, text):
        """
        Converts 'Expression(N)' to 'Expression.shift(N)'.
        Examples: 
        - df['close'](1) -> df['close'].shift(1)
        - MyVar(2) -> MyVar.shift(2)
        - BUT ignores: shift(1), rolling(20), mean(5), etc. to support native pandas syntax.
        """
        # Regex to match: (df\['[^']+'\]|[a-zA-Z_]\w*)\s*\((\d+)\)
        # Added negative lookahead to exclude common pandas methods
        # excluded: shift, rolling, ewm, expanding, diff, pct_change, mean, std, sum, min, max, count, var, median
        
        exclusions = "shift|rolling|ewm|expanding|diff|pct_change|mean|std|sum|min|max|count|var|median"
        # Match word that is NOT in exclusion list
        # We look for:
        # 1. df['...'] (always match)
        # OR
        # 2. word that is not excluded
        
        # Regex updated to handle whitespace inside parentheses: e.g. "Var( 1 )"
        pattern = rf"(df\['[^']+'\]|\b(?!(?:{exclusions})\b)[a-zA-Z_]\w*)\s*\(\s*(\d+)\s*\)"
        
        def repl(match):
            expr = match.group(1)
            shift = match.group(2)
            return f"{expr}.shift({shift})"
            
        return re.sub(pattern, repl, text)

    def _map_vars_in_str(self, text):
        """Replace single-letter variables in string with DataFrame references."""
        # Use simple replacement but respect word boundaries
        # And ignoring already quoted strings or function parts?
        # We assume formula doesn't have strings.
        
        # Map tokens
        mapping = {
            'C': "df['close']",
            'O': "df['open']",
            'H': "df['high']",
            'L': "df['low']",
            'V': "df['volume']",
            'AMT': "df['amount']",
            '거래대금': "df['amount']",
            '거래량': "df['volume']"
        }
        
        # Regex to match separate words C, O, H, L, V
        # (?<!['".\w]) means not preceded by quote, dot or word char
        # (?!['"\w]) means not followed by quote or word char (ALLOW dot!)
        for k, v in mapping.items():
            pattern = pk = rf"(?<!['\".\w]){k}(?!['\"\w])"
            # Case insensitive for c, o, h, l, v?
            # Kiwoom is usually uppercase C. Let's support both if needed, 
            # but usually C is standard.
            text = re.sub(pattern, v, text)
            # Support lowercase too?
            pattern_lower = rf"(?<!['\".\w]){k.lower()}(?!['\"\w])"
            text = re.sub(pattern_lower, v, text)
            
        # Support user defined temp vars? 
        # If user defined "BBU = ...", we just use BBU.
        # But if they use BBU(1), we need to handle that.
        # _process_past_references handles "Var(N)".
        
        return text

    def _replace_function(self, text, func_name, replacement_fn):
        """
        Replaces function calls using a recursive parenthesis parser.
        This handles nested calls like CrossUp(C, avg(C, 20)).
        """
        # Case insensitive search for function name
        # We need to find "FuncName("
        lower_text = text.lower()
        lower_func = func_name.lower()
        
        start_idx = 0
        result = []
        last_pos = 0
        
        while True:
            # Find function start
            idx = lower_text.find(lower_func, start_idx)
            if idx == -1:
                break
                
            # check if it's a whole word (not SubCrossUp)
            if idx > 0 and (text[idx-1].isalnum() or text[idx-1] == '_'):
                start_idx = idx + len(lower_func)
                continue
                
            # Check opening paren
            open_paren_idx = lower_text.find('(', idx)
            if open_paren_idx == -1:
                start_idx = idx + len(lower_func)
                continue
                
            # Verify only whitespace between Name and (
            if open_paren_idx > idx + len(lower_func):
                between = text[idx + len(lower_func):open_paren_idx]
                if not between.strip() == "":
                    start_idx = open_paren_idx
                    continue
            
            # Found potential start. Now find matching closing paren.
            balance = 1
            close_paren_idx = -1
            current_pos = open_paren_idx + 1
            
            while current_pos < len(text):
                char = text[current_pos]
                if char == '(':
                    balance += 1
                elif char == ')':
                    balance -= 1
                    if balance == 0:
                        close_paren_idx = current_pos
                        break
                current_pos += 1
            
            if close_paren_idx != -1:
                # We found the full function call: func_name(...)
                # Extract arguments
                args_str = text[open_paren_idx+1 : close_paren_idx]
                
                # Split args by comma, respecting nested parens
                args = self._split_args(args_str)
                
                # Apply replacement
                replacement = replacement_fn(args)
                
                # Append text before this call
                result.append(text[last_pos:idx])
                # Append replacement
                result.append(replacement)
                
                last_pos = close_paren_idx + 1
                start_idx = last_pos
                # Re-sync lower_text if we modified length? 
                # Actually, we shouldn't modify text in-place while iterating indices based on original.
                # But here we are building 'result' and moving 'last_pos'.
                # We can't rely on 'idx' for next search if we want to support nested SAME function?
                # e.g. avg(avg(C, 10), 20)
                # Our recursive logic:
                # We found ONE instance. We replaced it.
                # Current logic finds outermost first? No, string find finds first occurrence.
                # avg(avg(C, 10), 20)
                # ^-- First find matches this 'avg'.
                # Arguments will be ["avg(C, 10)", "20"]
                # If we process replacement, the inner "avg(C, 10)" is passed to replacement_fn.
                # But replacement_fn expects "Source". 
                # If "Source" is "avg(C, 10)", and we wrap it: "avg(C, 10).rolling(20).mean()".
                # The inner avg is NOT processed yet!
                
                # CRITICAL: We need inner-first processing?
                # Or we recurse on args?
                # _process_expression calls _replace_function sequentially for distinct functions.
                # If we have nested SAME functions (avg inside avg),
                # finding the first 'avg' matches the OUTER one.
                # So args will contain the INNER 'avg' string.
                # We should RECURSIVELY process the args strings before using them?
                # Too complex to call full _process_expression there.
                
                # ALTERNATIVE: Use Regex with recursive pattern? Python re module doesn't support it fully.
                # BETTER APPROACH:
                # Keep the loop. But when we get Args, we check if they contain the function we are currently processing?
                # Or simply:
                # Run the whole pass multiple times until no changes?
                # Or process right-to-left? (Last occurrence first).
                # Right-to-left is better for finding inner-most first?
                # "avg(avg(C, 10), 20)"
                # Search 'avg'.
                # If we scan from right/end, we find the inner 'avg' first?
                # No, "avg(..., 20)" - the inner one is in the middle.
                
                # Let's try to handle nested cases by running the function parser 
                # multiple times if changes occurred? 
                # But that is inefficient.
                
                # Let's inspect how _replace_function is called.
                # We call it for 'avg'.
                # If 'avg' is nested, we need to resolve inner first.
                # Solution:
                # In this loop, instead of finding first, find LAST?
                # Or check if any arg contains the function name again?
                
                # Simplest robust way for this scale:
                # Just recurse on the extracted args?
                # Yes: For each arg, call self._process_expression(arg) AGAIN?
                # That handles EVERYTHING inside the args.
                # But we might double-process?
                # _process_expression does EVERYTHING.
                # If we call it on arg, it might re-map variables.
                # C -> df['close']. If done twice? df['close'] -> df['df['close']'] ??
                # Step 1 maps C -> df['close'].
                # If we call _process_expression on "df['close']", Step 1 will see no 'C'. Good.
                # Step 2 sees df['close'](1). Good.
                
                # So: When extracting arguments for a function,
                # we should recursively convert those arguments.
                
                # However, this current method `_replace_function` is just one step in pipeline.
                # If we call `_process_expression` (full pipeline) inside `_replace_function`, 
                # we might get infinite loops or order issues.
                
                # Better: In `_process_expression`, we do transformation passes.
                # For `_replace_function`, since we want inner-first:
                # We can implement a "parse from inside out" strategy using a stack?
                # Or just use the simple fact:
                # If we process args recursively within `_replace_function` using ONLY `_replace_function` (self call)?
                
                # Let's stick to the Plan B:
                # We just do string manipulation.
                # For nested same-type functions: "avg(avg(C,10),20)"
                # If we simply match "avg(", we match the outer one.
                # Args: "avg(C,10)", "20".
                # If we assume args are just strings, we produce "avg(C,10).rolling..." - logic breaks.
                
                # Current Logic Improvement:
                # When we identify a function call `Func(...)`, we immediately search inside the args
                # for more instances of `Func`?
                # No, we just need to ensure we process inner ones first.
                # Inner ones always end before outer ones end.
                # They also start after outer ones start.
                
                # If we use a stack-based parser for the WHOLE string, that's best.
                # But that's writing a full parser.
                
                # Quick Fix for Nesting:
                # Find the 'avg' that has NO other 'avg' opening inside it?
                # Iterate until no 'avg' format remains.
                
                # Function: recursive_replace
                # content = text
                # while True:
                #    match = find_innermost_call(content, func_name)
                #    if not match: break
                #    replace(match)
                
                # find_innermost:
                # Find all 'avg(' indices.
                # Pick the one that doesn't contain another 'avg(' before its closing ')'?
                # Actually, innermost means it has no 'avg(' inside its scope.
                
                # Let's implement this "Repeated Replacement" approach within _replace_function.
                # We restart the search after every replacement?
                # But we need to ensure we don't re-process valid output.
                # "df.rolling" doesn't look like "avg(". So it's safe!
                
                # So loop strategy:
                # Find "avg(" from start. 
                # Check if it contains nested "avg(".
                # If yes, process the nested one FIRST.
                # If no, process this one.
                # Repeat.
                
                pass
            
            else:
                # No closing paren found - ignore or break
                break

        # Re-assemble only if we did something
        # But wait, the while loop structure above was for "process once".
        # Let's rewrite _replace_function to be robust for nesting.
        return self._replace_function_nested(text, func_name, replacement_fn)

    def _wrap_logical_operators(self, text):
        """
        Splits text by || (OR) and && (AND) recursively,
        wraps each atomic condition in parentheses, and joins with Python bitwise ops (| and &).
        """
        # 1. Split by ||
        or_chunks = self._split_balanced(text, '||')
        if len(or_chunks) > 1:
            processed = [self._wrap_logical_operators(chunk) for chunk in or_chunks]
            return " | ".join(processed)
        
        # 2. Split by &&
        and_chunks = self._split_balanced(text, '&&')
        if len(and_chunks) > 1:
            processed = [self._wrap_logical_operators(chunk) for chunk in and_chunks]
            return " & ".join(processed)
        
        # 3. Base case (Atom)
        atom = text.strip()
        if not atom: return atom
        
        # Detect fully wrapped (...) to avoid double wrapping
        if atom.startswith('(') and atom.endswith(')'):
            depth = 0
            is_pair = True
            for i, char in enumerate(atom):
                if char == '(': depth += 1
                elif char == ')': depth -= 1
                if depth == 0 and i < len(atom) - 1:
                    is_pair = False
                    break
            
            if is_pair:
                # Already wrapped, just recurse inside to handle potential && / ||
                inner = atom[1:-1]
                return f"({self._wrap_logical_operators(inner)})"
        
        # Wrap atom only if it contains logical operators or if explicitly needed
        # But for precedence safety, we generally wrap. 
        # To avoid infinite growth: if it's just a variable or number, don't wrap twice.
        if re.match(r'^(df\[\'[^\']+\'\]|[a-zA-Z_]\w*|\d+(\.\d+)?)$', atom):
            return atom
            
        return f"({atom})"

    def _split_balanced(self, text, delimiter):
        """
        Splits text by delimiter (e.g. '||') but ignores delimiters inside parentheses.
        """
        parts = []
        current = []
        balance = 0
        i = 0
        d_len = len(delimiter)
        
        while i < len(text):
            # Check delimiter match
            if balance == 0 and text[i:i+d_len] == delimiter:
                parts.append("".join(current).strip())
                current = []
                i += d_len
                continue
            
            char = text[i]
            if char == '(':
                balance += 1
            elif char == ')':
                balance -= 1
            
            current.append(char)
            i += 1
            
        parts.append("".join(current).strip())
        return parts

    def _replace_function_nested(self, text, func_name, replacement_fn):
        """
        Handles nested function calls by correctly identifying valid parenthesis scopes.
        Processes from left to right, but handles nesting by always picking the innermost first.
        """
        lower_func = func_name.lower()
        limit = 500 # Safety break for infinite loops
        
        while limit > 0:
            limit -= 1
            lower_text = text.lower()
            starts = []
            idx = 0
            while True:
                idx = lower_text.find(lower_func, idx)
                if idx == -1: break
                
                # Check boundaries: Whole word check
                # Prefix check
                if idx == 0 or (not text[idx-1].isalnum() and text[idx-1] not in ['_', '.']):
                    # Check for opening parenthesis
                    op = lower_text.find('(', idx)
                    if op != -1:
                        # Ensure only whitespace between name and (
                        between = text[idx+len(lower_func):op]
                        if not between.strip():
                            starts.append((idx, op))
                idx += 1
            
            if not starts:
                break
                
            # Pick the innermost call
            target_info = None 
            for f_start, f_open in starts:
                # Find matching closing parenthesis
                balance = 1
                close_idx = -1
                for i in range(f_open + 1, len(text)):
                    if text[i] == '(': balance += 1
                    elif text[i] == ')': balance -= 1
                    if balance == 0:
                        close_idx = i
                        break
                
                if close_idx == -1: continue 
                
                # Is there any other function start inside this one?
                has_nested = False
                for other_s, _ in starts:
                    if f_start < other_s < close_idx:
                        has_nested = True
                        break
                
                if not has_nested:
                    # Innermost found
                    args_str = text[f_open+1:close_idx]
                    target_info = (f_start, close_idx, args_str)
                    break 
            
            if target_info:
                start, end, content = target_info
                args = self._split_args(content)
                
                # Only wrap logical operators if necessary
                processed_args = []
                for a in args:
                    if '&&' in a or '||' in a:
                        processed_args.append(self._wrap_logical_operators(a))
                    else:
                        processed_args.append(a)
                
                repl = replacement_fn(processed_args)
                
                # If replacement is identical, stop to avoid infinite loop
                if text[start:end+1] == repl:
                    break
                    
                text = text[:start] + repl + text[end+1:]
            else:
                break
        return text

    def _split_args(self, args_str):
        """Split arguments by comma, ignoring commas inside parentheses."""
        args = []
        balance = 0
        current = []
        
        for char in args_str:
            if char == ',' and balance == 0:
                args.append("".join(current).strip())
                current = []
            else:
                if char == '(': balance += 1
                elif char == ')': balance -= 1
                current.append(char)
        
        args.append("".join(current).strip())
        return args

    def _preprocess_korean_vars(self, formula):
        """
        한글 변수명을 영어 placeholder로 치환하되, '당일시가' 등 시스템 예약어는 우선 처리합니다.
        """
        # [안실장 픽스] 시스템 예약한글 키워드 우선 매핑
        special_keywords = {
            "당일시가": "day_open",
            "전일종가": "prev_close",
            "시가": "O",
            "고가": "H",
            "저가": "L",
            "현재가": "C",
            "종가": "C",
            "거래량": "V",
            "거래대금": "AMT"
        }
        
        # 1. 시스템 예약어 우선 치환 (단어 경계 확인)
        processed_formula = formula
        for k_word, e_word in special_keywords.items():
            processed_formula = re.sub(rf'\b{k_word}\b', e_word, processed_formula)

        # 2. 일반 한글 사용자 정의 변수 처리 (나머지 한글)
        tokens = re.findall(r'[a-zA-Z0-9_\uac00-\ud7a3]+', processed_formula)
        
        korean_tokens = set()
        for t in tokens:
            if any('\uac00' <= c <= '\ud7a3' for c in t):
                korean_tokens.add(t)
        
        sorted_tokens = sorted(list(korean_tokens), key=len, reverse=True)
        
        for idx, token in enumerate(sorted_tokens):
            eng_var = f"_KVAR_{idx}"
            self.korean_var_map[eng_var] = token
            processed_formula = re.sub(rf'\b{token}\b', eng_var, processed_formula)
            
        return processed_formula

if __name__ == "__main__":
    parser = FormulaParser()
    
    # Test 1: Simple CrossUp
    print("=== Test 1: Simple CrossUp ===")
    formula1 = "CrossUp(C, avg(C, 20))"
    print(f"Formula: {formula1}")
    print("Python Code:")
    print(parser.parse(formula1))
    print()
    
    # Test 2: Nested Average
    print("=== Test 2: Nested Average ===")
    formula2 = "avg(avg(C, 10), 20)"
    print(f"Formula: {formula2}")
    print("Python Code:")
    print(parser.parse(formula2))
    print()
    
    # Test 3: Complex
    print("=== Test 3: Complex 3 ===")
    formula3 = "CrossUp(ma(C, 5), ma(C, 20))"
    print(f"Formula: {formula3}")
    print("Python Code:")
    print(parser.parse(formula3))
