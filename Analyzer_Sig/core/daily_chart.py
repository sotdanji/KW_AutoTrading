import datetime
from .config import get_api_config
from shared.api import fetch_daily_chart, fetch_index_chart

def get_daily_chart(stk_cd, start_date='', end_date='', cont_yn='N', next_key='', token=None, max_retries=3):
	conf = get_api_config()
	return fetch_daily_chart(conf['host_url'], stk_cd, token, days=1, base_dt=end_date)

def get_daily_chart_continuous(stk_cd, token, days=200, end_date=''):
	conf = get_api_config()
	return fetch_daily_chart(conf['host_url'], stk_cd, token, days=days, base_dt=end_date)

def get_index_chart_continuous(index_cd, token=None, days=600):
	conf = get_api_config()
	return fetch_index_chart(conf['host_url'], index_cd, token, days=days)

