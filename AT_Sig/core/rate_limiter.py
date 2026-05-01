import time
import threading

class RateLimiter:
    """
    Token Bucket Algorithm for Rate Limiting.
    Thread-safe.
    """
    def __init__(self, rate_limit=5.0, time_window=1.0):
        """
        :param rate_limit: Max requests allowed per time_window
        :param time_window: Time window in seconds (default 1s)
        """
        self.rate_limit = rate_limit
        self.time_window = time_window
        self.tokens = rate_limit
        self.last_check = time.time()
        self.lock = threading.Lock()

    def wait_for_token(self):
        """
        Blocks until a token is available.
        """
        with self.lock:
            while True:
                current_time = time.time()
                elapsed = current_time - self.last_check
                
                # Refill tokens
                if elapsed > 0:
                    # Calculate how many tokens to add
                    # e.g. 5 tokens / 1 sec * 0.5 sec elapsed = 2.5 tokens
                    new_tokens = elapsed * (self.rate_limit / self.time_window)
                    self.tokens = min(self.rate_limit, self.tokens + new_tokens)
                    self.last_check = current_time
                
                if self.tokens >= 1:
                    self.tokens -= 1
                    return # Permitted
                else:
                    # Wait for enough time to get at least 1 token
                    # needed = 1 - current_tokens
                    # time_needed = needed / (rate / window)
                    needed = 1 - self.tokens
                    refresh_rate = self.rate_limit / self.time_window
                    if refresh_rate > 0:
                        sleep_time = needed / refresh_rate
                    else:
                        sleep_time = 1 # Fallback, should not happen
                    
                    # Release lock while sleeping
                    self.lock.release()
                    time.sleep(sleep_time)
                    self.lock.acquire()
                    # Re-check loop
