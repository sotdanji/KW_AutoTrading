import requests
import json
from .config import get_api_config

def get_access_token():
    """
    Combines logic to get the access token from Kiwoom REST API.
    Returns:
        token (str): Access token if successful, None otherwise.
    """
    conf = get_api_config()
    host_url = conf['host_url']
    app_key = conf['app_key']
    app_secret = conf['app_secret']

    url = f"{host_url}/oauth2/token"
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8'
    }

    data = {
        'grant_type': 'client_credentials',
        'appkey': app_key,
        'secretkey': app_secret
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            token = response.json().get('token')
            if token:
                print(f"Token received: {token[:10]}...")
                return token
            else:
                print("Token not found in response.")
                return None
        else:
            print(f"Login failed code: {response.status_code}")
            print(f"Body: {response.text}")
            return None

    except requests.exceptions.Timeout:
        print("Error: Login request timed out. 네트워크 연결을 확인하세요.")
        return None
    except requests.exceptions.ConnectionError:
        print("Error: 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.")
        return None
    except Exception as e:
        print(f"Error during login request: {e}")
        return None

if __name__ == '__main__':
    token = get_access_token()
    print("Test Token:", token)
