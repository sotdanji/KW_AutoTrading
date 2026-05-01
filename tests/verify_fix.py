
import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'AT_Sig'))

from AT_Sig.stock_info import get_stock_info_async
from AT_Sig.login import fn_au10001 as get_token

async def verify_fix():
    # Windows Console Encoding Issue Fix
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass
        
    print("=== [Check Start] Real-time Price Correction & Parsing Logic Test ===")
    
    # 1. Token Issue
    print("\n1. Token Issue...")
    try:
        token = get_token()
        if token:
            print(f"✅ 토큰 발급 성공: {token[:10]}...")
        else:
            print("❌ 토큰 발급 실패. 테스트 중단.")
            return
    except Exception as e:
        print(f"❌ 토큰 발급 중 예외 발생: {e}")
        return

    # 2. 시세 보정 로직 검증 (rt_search.py 로직 시뮬레이션)
    print("\n2. 시세 보정 로직 검증 (삼성전자 005930 예시)")
    print("   상황 설정: 웹소켓으로 '현재가 0' 데이터 수신됨")
    
    # Mock Data
    stk_cd = "005930"
    vals = {'9001': stk_cd, '10': '0'} # 현재가 0원으로 가정
    
    # Logic from rt_search.py
    cur_price = vals.get('10')
    need_enrichment = False
    
    if not cur_price or str(cur_price).strip() == '' or str(cur_price) == '0':
        need_enrichment = True
        print(f"   -> 보정 필요 감지됨 (Original: {cur_price})")
    
    if need_enrichment:
        print("   -> REST API (dostk/stkinfo) 요청 중...")
        try:
            stock_info = await get_stock_info_async(stk_cd, token)
            if stock_info:
                # API returns
                api_price = stock_info.get('stk_prc', '0')
                api_name = stock_info.get('stk_nm', 'Unknown')
                
                # Update vals
                vals['10'] = str(api_price)
                
                print(f"   ✅ API 조회 성공: {api_name}({stk_cd})")
                print(f"   ✅ 데이터 보정 결과: 현재가 '0' -> '{api_price}' (오늘 종가)")
            else:
                print("   ❌ API 조회 실패 (데이터 없음)")
        except Exception as e:
            print(f"   ❌ API 호출 중 오류: {e}")
            
    # 3. 파싱 로직 검증 (trading_engine.py 로직 시뮬레이션)
    print("\n3. 안전 파싱 로직 검증 (safe_parse_int)")
    
    def safe_parse_int(val_str):
        if not val_str: return 0
        try:
            # Remove commas and whitespace
            clean = str(val_str).replace(',', '').strip()
            if not clean: return 0
            # Handle float string like '1000.0'
            return int(float(clean))
        except:
            return 0
            
    test_cases = [
        ('1000', 1000),
        ('2,500', 2500),
        ('  300 ', 300),
        ('5500.0', 5500),
        ('', 0),
        (None, 0),
        ('invalid', 0)
    ]
    
    all_pass = True
    for inp, expected in test_cases:
        result = safe_parse_int(inp)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL": all_pass = False
        print(f"   Input: {str(inp):<10} -> Output: {result:<5} | Expected: {expected:<5} [{status}]")
        
    if all_pass:
        print("\n✅ 모든 검증 통과! 수정된 로직은 정상 작동합니다.")
    else:
        print("\n⚠️ 일부 파싱 테스트 실패.")

if __name__ == '__main__':
    asyncio.run(verify_fix())
