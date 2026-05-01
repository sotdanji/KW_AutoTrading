import requests
import json
import datetime
import time
from .config import get_api_config

def get_daily_chart(stk_cd, start_date='', end_date='', cont_yn='N', next_key='', token=None, max_retries=3):
    """
    Fetches daily chart data from Kiwoom API with retry logic for rate limits.
    Single page query (for backward compatibility).
    """
    conf = get_api_config()
    host_url = conf['host_url']
    url = f"{host_url}/api/dostk/chart"
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10081',
    }
    
    if not end_date:
        end_date = datetime.datetime.now().strftime("%Y%m%d")

    params = {
        'stk_cd': stk_cd,
        'base_dt': end_date,
        'upd_stkpc_tp': '1',
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=params, timeout=10)
            
            # Handle 429 rate limit error with exponential backoff
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    wait_time = 2 ** attempt
                    print(f"[WARN] Rate limit hit for {stk_cd}, waiting {wait_time}s before retry {attempt+1}/{max_retries}...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Give up after max retries
                    print(f"[ERROR] Rate limit exceeded for {stk_cd} after {max_retries} attempts, skipping...")
                    return []
            
            if response.status_code != 200:
                print(f"Daily chart request failed: {response.status_code}")
                return []
                
            data = response.json()
            
            # Use correct API response key
            chart_data = data.get('stk_dt_pole_chart_qry', [])
            if not chart_data:
                chart_data = data.get('output', [])
                
            return chart_data
            
        except Exception as e:
            if attempt < max_retries - 1:
                # Wait before retry with exponential backoff
                wait_time = 2 ** attempt
                print(f"[WARN] Error fetching data for {stk_cd}, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"Error fetching daily chart after retries: {e}")
                return []
    
    return []


def get_daily_chart_continuous(stk_cd, token, days=200, end_date=''):
    """
    Fetches daily chart data with continuous query (pagination) support.
    Based on Ch6/min_pole_con.py pattern.
    
    Args:
        stk_cd: Stock code
        token: API token
        days: Number of days to fetch (default: 200)
        end_date: End date in YYYYMMDD format (default: today)
    
    Returns:
        list: Chart data (up to 'days' items)
    """
    conf = get_api_config()
    host_url = conf['host_url']
    url = f"{host_url}/api/dostk/chart"
    
    if not end_date:
        end_date = datetime.datetime.now().strftime("%Y%m%d")
    
    all_data = []
    cont_yn = 'N'
    next_key = ''
    max_iterations = 50  # Safety limit to prevent infinite loop
    iteration = 0
    
    try:
        while len(all_data) < days and iteration < max_iterations:
            iteration += 1
            
            headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'authorization': f'Bearer {token}',
                'cont-yn': cont_yn,
                'next-key': next_key,
                'api-id': 'ka10081',
            }
            
            params = {
                'stk_cd': stk_cd,
                'base_dt': end_date,
                'upd_stkpc_tp': '1',
            }
            
            response = requests.post(url, headers=headers, json=params, timeout=10)
            
            # Handle rate limit
            if response.status_code == 429:
                print(f"[WARN] Rate limit hit for {stk_cd}, waiting 1 second...")
                time.sleep(1)
                continue
            
            if response.status_code != 200:
                print(f"[ERROR] API error {response.status_code} for {stk_cd}")
                break
            
            data = response.json()
            
            # Extract chart data
            chart_data = data.get('stk_dt_pole_chart_qry', [])
            if not chart_data:
                chart_data = data.get('output', [])
            
            if not chart_data:
                break  # No more data
            
            all_data.extend(chart_data)
            
            # Check for next page (from response headers)
            cont_yn = response.headers.get('cont-yn', 'N')
            next_key = response.headers.get('next-key', '')
            
            # Exit if no more pages
            if cont_yn != 'Y' or not next_key:
                break
            
            # Wait between requests to avoid rate limit
            if len(all_data) < days:
                time.sleep(0.5)
        
        # Return only the requested number of days
        return all_data[:days]
        
    except Exception as e:
        print(f"[ERROR] Continuous query failed for {stk_cd}: {e}")
        return all_data if all_data else []
