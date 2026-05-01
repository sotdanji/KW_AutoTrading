import os
import sys
import pandas as pd
import numpy as np

at_sig_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if at_sig_dir not in sys.path:
    sys.path.insert(0, at_sig_dir)

from data_manager import DataManager
from shared.indicators import TechnicalIndicators as TI

def analyze_402490():
    dm = DataManager()
    stk_cd = "402490" # 그린리소스
    
    # 1. 일봉 데이터 가져오기 (충분히)
    df_list = dm.get_daily_chart(stk_cd, count=100)
    if not df_list:
        print("Data not found")
        return
    
    df = TI.preprocess_data(df_list)
    C, O, H, L, V = df['close'], df['open'], df['high'], df['low'], df['volume']
    
    # 2. 전략 조건식 (원래 수식 그대로)
    BBU1 = TI.bbands(C, 20, 2)[0]
    BBU2 = TI.bbands(C, 60, 2)[0]
    
    A1 = (C.shift(2)>BBU1.shift(2)) | (C.shift(1)>BBU1.shift(1)) | (C>BBU1)
    A2 = (C.shift(2)>BBU2.shift(2)) | (C.shift(1)>BBU2.shift(1)) | (C>BBU2)
    
    A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
    A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
    A5 = (O>C) # 오늘이 음봉
    
    B = A1 & A2 & A3 & A4 & A5
    
    # [Original Logic] ValueWhen(1, B, O)
    TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
    
    # [New Max Logic] Highest in 60 days
    B_rec = B.copy()
    B_rec.iloc[:-60] = False
    Max_TL_val = O[B_rec].max() if B_rec.any() else 0
    
    # 결과 출력
    print(f"--- [그린리소스 (402490)] 분석 결과 ---")
    print(f"현재가: {C.iloc[-1]:,}")
    
    # 최근 10일간의 B 발생 여부와 TargetLine 변화 확인
    last_10 = df.tail(15).copy()
    last_10['B_Signal'] = B.tail(15)
    last_10['TargetLine'] = TargetLine.tail(15)
    
    print("\n[최근 15일 흐름]")
    print(last_10[['dt', 'open', 'close', 'B_Signal', 'TargetLine']].to_string(index=False))
    
    last_B_idx = B[B].index[-1] if B.any() else None
    if last_B_idx is not None:
        last_B_date = df.loc[last_B_idx, 'dt']
        last_B_price = df.loc[last_B_idx, 'open']
        print(f"\n✅ 가장 최근 패턴 발생일(ValueWhen): {last_B_date} (시가: {last_B_price:,}원)")
        print(f"✅ 현재 TargetLine(ValueWhen): {TargetLine.iloc[-1]:,}원")
        print(f"✅ 최고가 TargetLine(Max 60d): {Max_TL_val:,}원")

if __name__ == "__main__":
    analyze_402490()
