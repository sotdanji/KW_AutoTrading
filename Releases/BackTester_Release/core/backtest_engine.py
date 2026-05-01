import pandas as pd
import datetime
import time
from .strategy_signal import process_data, check_signal_at
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

class BacktestEngine(QObject):
    # Signals to update UI
    progress_updated = pyqtSignal(int, int) # current, total
    log_message = pyqtSignal(str)
    trade_executed = pyqtSignal(dict)
    finished = pyqtSignal(dict) # Summary

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.running = False
        
    def run(self, stock_list, start_date, end_date, config, preloaded_data=None, headless=False):
        self.running = True
        
        # 1. Data Preparation Phase
        market_data = {}
        if preloaded_data:
            market_data = preloaded_data.copy()
        
        valid_stocks = []
        total_stocks = len(stock_list)
        
        # Determine stocks to fetch
        stocks_to_fetch = [s for s in stock_list if s not in market_data]
        
        if not headless and stocks_to_fetch:
            self.log_message.emit(f"Fetching data for {len(stocks_to_fetch)} stocks...")
        
        for idx, code in enumerate(stocks_to_fetch):
            if not self.running: break
            
            if not headless:
                # Update progress for fetching
                self.progress_updated.emit(idx + 1, len(stocks_to_fetch))
                QApplication.processEvents()
            
            # Fetch logic
            today = datetime.date.today()
            if hasattr(start_date, 'toPyDate'):
                s_date_py = start_date.toPyDate()
            else:
                s_date_py = start_date
                
            days_needed = (today - s_date_py).days + 1000
            if days_needed < 200: days_needed = 200
            
            fetched_df, error = process_data(code, self.token, days=days_needed)
            
            if fetched_df is not None:
                fetched_df['date_str'] = pd.to_datetime(fetched_df['date']).dt.strftime('%Y%m%d')
                fetched_df.set_index('date_str', inplace=True)
                market_data[code] = fetched_df
            else:
                if not headless:
                    self.log_message.emit(f"[{code}] Fetch Error: {error}")
            
            # Rate limit
            if not headless:
                time.sleep(0.2)
                
        if not self.running: return

        # 2. Simulation Phase
        if not headless:
            self.log_message.emit("Running Simulation...")
            
        from .simulation_core import SimulationCore
        
        # Run Simulation
        summary = SimulationCore.run(stock_list, start_date, end_date, config, market_data)
        
        # 3. Report Results
        if not headless:
            # Reconstruct trades for UI log (SimulationCore returns full trade list)
            for trade in summary['trades']:
                self.trade_executed.emit(trade)
                self.log_message.emit(f"{trade['status']} {trade['code']} ({trade['profit_pct']:.2f}%)")
                
            self.log_message.emit(f"========== 백테스트 완료 ==========")
            self.log_message.emit(f"총 손익: {summary['total_profit']:+,.0f}원 ({summary['return_pct']:+.2f}%)")
            self.log_message.emit(f"승률: {summary['win_rate']:.1f}%")
            self.log_message.emit(f"===================================")
            
        self.finished.emit(summary)
        self.running = False
        
    def stop(self):
        self.running = False

