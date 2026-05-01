import requests
import json
from config import get_current_config
from shared.api import get_token

# 접근토큰 발급
def fn_au10001():
    conf = get_current_config()
    return get_token(conf['host_url'], conf['app_key'], conf['app_secret'])

# 실행 구간
if __name__ == '__main__':
    token = fn_au10001()
    print("토큰: ", token)