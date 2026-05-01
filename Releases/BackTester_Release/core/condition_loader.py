import asyncio
import websockets
import json
from .config import get_api_config

class WebSocketClient:
    def __init__(self, uri):
        self.uri = uri
        self.websocket = None
        self.connected = False
        self.received_data = None
        self.error = None

    async def connect(self, token):
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            
            # Login
            param = {
                'trnm': 'LOGIN',
                'token': token
            }
            await self.send_message(param)
        except Exception as e:
            print(f'Connection error: {e}')
            self.error = str(e)
            self.connected = False

    async def send_message(self, message):
        if self.connected:
            if not isinstance(message, str):
                message = json.dumps(message)
            await self.websocket.send(message)

    async def receive_once(self, timeout=3.0):
        """Receives a single relevant data packet or timeout."""
        try:
            start_time = asyncio.get_event_loop().time()
            while True:
                # Check for timeout manually or use asyncio.wait_for on recv
                # Using wait_for on each recv is safer
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    self.error = "Timeout waiting for response"
                    return None
                
                response = json.loads(message)
                
                trnm = response.get('trnm')
                if trnm == 'LOGIN':
                    if response.get('return_code') != 0:
                        self.error = f"Login Failed: {response.get('return_msg')}"
                        return None
                elif trnm == 'PING':
                    await self.send_message(response)
                elif trnm == 'CNSRREQ':  # Response for condition request (Snapshot)
                    data = response.get('data')
                    # if data is None but trnm matched, it might be empty result.
                    # Usually data structure: {'index': 0, 'data': [...]}
                    # Kiwoom mock server might return just {'trnm': 'CNSRREQ', 'data': [...]}
                    self.received_data = data if data else []
                    return self.received_data
                else:
                    # Target Data (Generic)
                    data = response.get('data')
                    if data:
                        self.received_data = data
                        return data
                
                # Check total elapsed time if we got ping or other non-target msg
                if asyncio.get_event_loop().time() - start_time > timeout:
                    self.error = "Total operation timeout"
                    return None

        except Exception as e:
            self.error = str(e)
            return None
        finally:
             if self.websocket:
                await self.websocket.close()

async def fetch_condition_list(token):
    """
    Fetches the list of condition formulas from Kiwoom API.
    Returns:
        dict: The condition list data, or None if failed.
    """
    try:
        conf = get_api_config()
        socket_url = conf.get('socket_url', 'wss://mockapi.kiwoom.com:10000') # Default fallback
        ws_url = f"{socket_url}/api/dostk/websocket"
        
        client = WebSocketClient(ws_url)
        await client.connect(token)
        
        if not client.connected:
            return None

        # Request Condition List (CNSRLST)
        await client.send_message({'trnm': 'CNSRLST'})
        
        # Wait for response
        return await client.receive_once()
        
    except Exception as e:
        print(f"Error fetching conditions: {e}")
        return None

async def fetch_stock_list(token, seq_idx):
    """
    Fetches the list of stocks for a specific condition index.
    """
    try:
        conf = get_api_config()
        socket_url = conf.get('socket_url', 'wss://mockapi.kiwoom.com:10000')
        ws_url = f"{socket_url}/api/dostk/websocket"
        
        client = WebSocketClient(ws_url)
        await client.connect(token)
        
        if not client.connected:
            return None

        # Request Condition Stock List (CNSRREQ)
        # Assuming search_type '1' (General) and stex_tp 'K' (KOSPI/KOSDAQ)
        param = { 
            'trnm': 'CNSRREQ', 
            'seq': str(seq_idx), 
            'search_type': '1', 
            'stex_tp': 'K'
        }
        await client.send_message(param)
        
        # Wait for response with timeout
        data = await client.receive_once(timeout=5.0)
        
        # Parse stock code list from data
        # Data format from Kiwoom WS for CNSRREQ usually contains a list of codes or similar
        # Validating format is needed. Assuming list of dicts or list of strings?
        # Based on API docs, it might be a list of items where each item has '9001' (Code)
        return data

    except Exception as e:
        print(f"Error fetching stock list: {e}")
        return None

def get_stock_list_sync(token, seq_idx):
    """Synchronous wrapper for fetch_stock_list"""
    try:
        return asyncio.run(fetch_stock_list(token, seq_idx))
    except Exception as e:
        print(f"Sync wrapper error: {e}")
        return None


def get_condition_list_sync(token):
    """Synchronous wrapper for fetch_condition_list"""
    try:
        return asyncio.run(fetch_condition_list(token))
    except Exception as e:
        print(f"Sync wrapper error: {e}")
        return None
