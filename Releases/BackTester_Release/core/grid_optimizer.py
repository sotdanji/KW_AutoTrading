"""
Simplified Grid Search Optimizer

Runs multiple backtests with different parameter combinations synchronously.
"""
from PyQt6.QtCore import QThread, pyqtSignal
import itertools
import datetime


class GridSearchWorker(QThread):
    """Worker thread for grid search optimization"""
    
    progress_updated = pyqtSignal(int, int, str)  # current, total, message
    result_found = pyqtSignal(dict)  # one test result
    optimization_finished = pyqtSignal(dict)  # best parameters
    
    def __init__(self, token, stock_codes, start_date, end_date, strategy_code, param_ranges):
        super().__init__()
        self.token = token
        self.stock_codes = stock_codes
        self.start_date = start_date
        self.end_date = end_date
        self.strategy_code = strategy_code
        self.param_ranges = param_ranges
        self.running = True
        
    def run(self):
        """Execute grid search"""
        from core.backtest_engine import BacktestEngine
        
        # Generate combinations
        sl_values = self.param_ranges['sl']
        tp_values = self.param_ranges['tp']
        ratio_values = self.param_ranges['ratio']
        
        combinations = list(itertools.product(sl_values, tp_values, ratio_values))
        total = len(combinations)
        
        best_result = None
        best_return = float('-inf')
        all_results = []
        
        for idx, (sl, tp, ratio) in enumerate(combinations):
            if not self.running:
                break
            
            # Create config
            config = {
                'deposit': 10000000,
                'sl': sl,
                'tp': tp,
                'ratio': ratio,
                'strategy_code': self.strategy_code
            }
            
            # Update progress
            msg = f"테스트 중: SL={sl}%, TP={tp}%, Ratio={ratio}%"
            self.progress_updated.emit(idx + 1, total, msg)
            
            # Run backtest synchronously
            engine = BacktestEngine(self.token)
            
            # Connect to capture result
            result_container = {'summary': None}
            
            def capture_result(summary):
                result_container['summary'] = summary
            
            engine.finished.connect(capture_result)
            engine.run(self.stock_codes, self.start_date, self.end_date, config)
            
            # Wait for completion (in real implementation, use proper synchronization)
            # For now, we'll use a simple approach
            engine.wait()  # This would need to be added to BacktestEngine
            
            summary = result_container.get('summary')
            if summary:
                return_pct = summary.get('return_pct', 0)
                
                result = {
                    'sl': sl,
                    'tp': tp,
                    'ratio': ratio,
                    'return_pct': return_pct,
                    'total_trades': summary.get('total_trades', 0),
                    'win_rate': summary.get('win_rate', 0)
                }
                
                all_results.append(result)
                self.result_found.emit(result)
                
                if return_pct > best_return:
                    best_return = return_pct
                    best_result = result
        
        # Emit best result
        if best_result:
            self.optimization_finished.emit(best_result)
        
        self.running = False
    
    def stop(self):
        """Stop optimization"""
        self.running = False
