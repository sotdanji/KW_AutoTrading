
import sys
import os
import asyncio
from datetime import datetime

# 프로젝트 루트를 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from data_manager import DataManager
from login import fn_au10001 as get_token
from strategy_runner import StrategyRunner
import pandas as pd

async def debug_bukwang():
    stk_cd = "003000" # 부광약품
    print(f"--- 부광약품({stk_cd}) 전략 체결 분석 시작 ---")
    
    token = get_token()
    if not token:
        print("토큰 발급 실패")
        return

    dm = DataManager()
    
    # 1. 일봉 데이터 조회 (GapUp 확인용)
    daily_data = dm.get_daily_chart(stk_cd, token)
    if not daily_data:
        print("일봉 데이터 조회 실패")
        return
    
    # daily_data: [today, yesterday, ...]
    today_open = float(daily_data[0]['stk_oprc'])
    yesterday_close = float(daily_data[1]['stk_prc'])
    is_gap_up = today_open > yesterday_close
    
    print(f"어제 종가: {yesterday_close:,}원")
    print(f"오늘 시가: {today_open:,}원")
    print(f"시가 갭 상승 여부(IsGapUp): {is_gap_up}")

    # 2. 분봉 데이터 조회 (음봉 및 돌파 확인용)
    min_data = dm.get_minute_chart(stk_cd, token, min_tp='1')
    if not min_data:
        print("분봉 데이터 조회 실패")
        return
    
    # 분봉 데이터를 DataFrame으로 변환 (StrategyRunner와 유사하게)
    df = pd.DataFrame(min_data)
    # API 결과 컬럼명 대응 (stk_cntg_hour, stk_prc 등)
    # fetch_minute_chart_ka10080 반환 형식을 따름
    df['time'] = df['stk_cntg_hour']
    df['close'] = df['stk_prc'].astype(float)
    df['open'] = df['stk_oprc'].astype(float)
    df['high'] = df['stk_hgpr'].astype(float)
    df['low'] = df['stk_lwpr'].astype(float)
    
    # 시간순 정렬
    df = df.sort_values(by='time').reset_index(drop=True)
    
    # 09:10 및 09:30 가격 확인
    row_10 = df[df['time'] <= '091000'].iloc[-1] if not df[df['time'] <= '091000'].empty else None
    row_30 = df[df['time'] <= '093000'].iloc[-1] if not df[df['time'] <= '093000'].empty else None
    
    if row_10 is not None:
        price_10 = row_10['close']
        is_10_neg = today_open > price_10
        print(f"09:10 종가: {price_10:,}원 | 음봉 여부: {is_10_neg}")
    else:
        print("09:10 데이터 없음")

    if row_30 is not None:
        price_30 = row_30['close']
        is_30_neg = today_open > price_30
        print(f"09:30 종가: {price_30:,}원 | 음봉 여부: {is_30_neg}")
    else:
        print("09:30 데이터 없음")

    # 3. 실시간 돌파 여부 확인
    # 09:10 이후 시가 돌파 시점 찾기
    break_10 = df[(df['time'] > '091000') & (df['close'] >= today_open)]
    if not break_10.empty:
        first_break_10 = break_10.iloc[0]['time']
        print(f"09:10 이후 시가 돌파 시점: {first_break_10}")
    else:
        print("09:10 이후 시가 돌파 없음")

    # 4. 종합 판단
    can_buy = is_gap_up and ((is_10_neg and not break_10.empty) or (is_30_neg and not df[(df['time'] > '093000') & (df['close'] >= today_open)].empty))
    print(f"\n최종 매수 조건 총족 여부: {can_buy}")
    
    if not can_buy:
        if not is_gap_up: print("사유: 시가 갭 상승 실패 (보합 또는 갭하락)")
        elif not (is_10_neg or is_30_neg): print("사유: 10분/30분 지점 모두 양봉 (음봉 소화 과정 없음)")
        else: print("사유: 음봉 조건은 맞으나 이후 시가 돌파(CrossUp)가 발생하지 않음")

if __name__ == "__main__":
    asyncio.run(debug_bukwang())
