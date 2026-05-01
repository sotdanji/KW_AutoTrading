from .config import get_api_config
from shared.api import get_token

def get_access_token():
	conf = get_api_config()
	return get_token(conf['host_url'], conf['app_key'], conf['app_secret'])

if __name__ == '__main__':
	token = get_access_token()
	print("Test Token:", token)
