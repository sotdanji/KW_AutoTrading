import os
import json

class AT_SigIntegrator:
    def __init__(self):
        # Path to AT_Sig's monitoring list or settings
        self.at_sig_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../AT_Sig"))
        self.watchlist_path = os.path.join(self.at_sig_root, "lead_watchlist.json")

    def add_to_watchlist(self, stock_info):
        """
        Adds a stock to the shared watchlist.
        Returns: True (success), 'duplicate' (already exists), 'missing' (AT_Sig not found)
        """
        if not os.path.exists(self.at_sig_root):
            return 'missing'

        watchlist = []
        if os.path.exists(self.watchlist_path):
            try:
                with open(self.watchlist_path, "r", encoding="utf-8") as f:
                    watchlist = json.load(f)
            except:
                watchlist = []

        # Check for duplicates
        if any(s['code'] == stock_info['code'] for s in watchlist):
            return 'duplicate'

        watchlist.append({
            'code': stock_info['code'], 
            'name': stock_info['name'],
            'weight': stock_info.get('weight', 1.0) # Default to 1.0
        })
        try:
            with open(self.watchlist_path, "w", encoding="utf-8") as f:
                json.dump(watchlist, f, ensure_ascii=False, indent=4)
            return True
        except:
            return False
