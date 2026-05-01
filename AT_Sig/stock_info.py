import json
import aiohttp
import asyncio
import time
from shared.api import fetch_kw_data

# 주식기본정보요청
def fn_ka10001(stk_cd, cont_yn='N', next_key='', token=None):
	"""(동기) 주식기본정보요청 - shared.api.fetch_kw_data 활용"""
	params = {'stk_cd': stk_cd}
	# shared/api.py의 통합 fetch 로직 사용 (Session 재사용 및 10054 대응)
	res = fetch_kw_data('/api/dostk/stkinfo', 'ka10001', params, token, mode="REAL")
	return res

async def get_stock_info_async(stk_cd, token, session=None, max_retries=3):
    """(비동기) 주식기본정보요청 -> (data, status_code) 반환 (Retry 로직 포함)"""
    from config import get_current_config
    conf = get_current_config()
    host_url = conf['host_url']
    url = host_url + '/api/dostk/stkinfo'
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': 'N',
        'api-id': 'ka10001',
    }
    params = {'stk_cd': stk_cd}
    
    for attempt in range(max_retries):
        try:
            # Use existing session or create one-off
            if session:
                async with session.post(url, headers=headers, json=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('output', None), 200
                    if resp.status == 429:
                        wait = (attempt + 1) * 5
                        await asyncio.sleep(wait)
                        continue
                    return None, resp.status
            else:
                async with aiohttp.ClientSession() as new_session:
                    async with new_session.post(url, headers=headers, json=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get('output', None), 200
                        if resp.status == 429:
                            wait = (attempt + 1) * 5
                            await asyncio.sleep(wait)
                            continue
                        return None, resp.status
        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError) as e:
            wait = (attempt + 1) * 2
            await asyncio.sleep(wait)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"주식정보 비동기 조회 최종 실패 ({stk_cd}): {e}")
            await asyncio.sleep(1)
            
    return None, 500

# 실행 구간
if __name__ == '__main__':
	fn_ka10001('005930', token=get_token())