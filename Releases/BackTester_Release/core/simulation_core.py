import pandas as pd
import datetime
import numpy as np

class SimulationCore:
    """
    Pure Python Backtest Simulation Engine.
    Decoupled from PyQt for multiprocessing compatibility.
    """
    
    @staticmethod
    def run(stock_list, start_date, end_date, config, market_data):
        """
        Run backtest for list of stocks.
        
        Args:
            stock_list (list): List of stock codes.
            start_date (QDate or datetime.date): Start date.
            end_date (QDate or datetime.date): End date.
            config (dict): Strategy config.
            market_data (dict): Preloaded data {code: DataFrame}.
            
        Returns:
            dict: Summary of results.
        """
        
        # Date Conversion safe check
        if hasattr(start_date, 'toPyDate'):
            s_date = start_date.toPyDate()
        else:
            s_date = start_date
            
        if hasattr(end_date, 'toPyDate'):
            e_date = end_date.toPyDate()
        else:
            e_date = end_date
            
        delta = e_date - s_date
        date_range = [s_date + datetime.timedelta(days=i) for i in range(delta.days + 1)]
        
        # Portfolio State
        cash = config.get('deposit', 10000000)
        initial_deposit = cash
        holdings = {} # {code: {'qty': 0, 'buy_price': 0, 'buy_date': ''}}
        trades = []
        
        # Pre-filter valid stocks (Must have data)
        valid_stocks = [res for res in stock_list if res in market_data]
        
        # Strategy Preparation
        strategy_code = config.get('strategy_code', '').strip()
        
        # Pre-calculate signals if strategy exists
        # To optimize, we add 'signal' column to dataframe copies
        # Note: In multiprocessing, make sure not to mutate shared memory destructively if possible, 
        # but here market_data is likely passed as copy or COW.
        
        processed_data = {}
        
        for code in valid_stocks:
            df = market_data[code]
            if df.empty: continue
            
            # We work on a view or copy to set signals
            # If strategy_code is provided, compute signals
            if strategy_code:
                try:
                    # Context needed for exec? 
                    # We need a standardized way to calc signal faster.
                    # For now, simplistic approach:
                    # Re-implementing Safe Execution Context is heavy.
                    # We assume params are simple. 
                    
                    # Optimization: Vectorized Signal Calculation?
                    # This is hard with arbitrary python code string.
                    # We will stick to the loop check or pre-calc if possible.
                    # Since existing engine did `exec` per Stock, let's do it here per stock (Vectorized potentially)
                    
                    # BUT, "Condition" usually depends on current row.
                    # Most Kiwoom formulas are vectorized naturally (Series > Series).
                    
                    from .execution_context import get_execution_context
                    exec_context = get_execution_context(df)
                    local_vars = {}
                    local_vars.update(exec_context)
                    
                    exec(strategy_code, {}, local_vars)
                    
                    if 'cond' in local_vars:
                        cond = local_vars['cond']
                        # Safe copy only once
                        df = df.copy()
                        
                        if isinstance(cond, pd.Series):
                            # [Look-ahead Bias Fix]
                            # General signals (calculated based on Close) should be executed on Next Open.
                            # Therefore, we SHIFT the signal by 1 day.
                            # Today's signal -> Becomes Tomorrow's Action
                            
                            # However, if 'target_price' strategy (Intraday Breakout), 
                            # the signal is usually 'Close > Target' (which is retroactive)
                            # OR 'High > Target' (Intraday).
                            # If usage is 'High > Target', we buy at Target TODAY.
                            
                            is_intraday = 'target_price' in local_vars
                            
                            if is_intraday:
                                # Intraday Strategy: No Shift (Signal implies 'Trade Today' condition met)
                                df['signal'] = cond.fillna(False)
                            else:
                                # End-of-Day Strategy: Shift 1 Day (Trade Tomorrow Open)
                                df['signal'] = cond.shift(1).fillna(False)
                            
                        # Check for target_price (Larry Williams Support)
                        if 'target_price' in local_vars:
                            tp_series = local_vars['target_price']
                            if isinstance(tp_series, pd.Series):
                                df['target_price'] = tp_series
                        
                        processed_data[code] = df
                except Exception as e:
                    # Strategy Error, skip functionality or treat as False
                    print(f"[ERROR] Strategy Execution Failed for {code}: {e}")
                    import traceback
                    traceback.print_exc()
                    processed_data[code] = df.copy()
                    processed_data[code]['signal'] = False
            else:
                # No Strategy -> Buy on first day (Logic from original)
                processed_data[code] = df
        
        
        # Simulation Loop
        for current_date in date_range:
            date_str = current_date.strftime("%Y%m%d")
            
            # 1. Processing Holdings (Sell)
            active_codes = list(holdings.keys()) # Copy keys
            for code in active_codes:
                pos = holdings[code]
                df = processed_data.get(code)
                if df is None or date_str not in df.index: continue
                
                # Fast lookup
                try:
                    row_close = df.at[date_str, 'close']
                    row_open = df.at[date_str, 'open']
                    row_high = df.at[date_str, 'high']
                    row_low = df.at[date_str, 'low']
                except KeyError:
                     continue
                
                # Setup Variables
                sl = config.get('sl', -3.0)
                tp = config.get('tp', 6.0)
                exit_on_open = config.get('exit_on_open', False)
                
                reason = ""
                sold = False
                sell_price = row_close
                
                # A. Time-based Exit (Sell on Next Day Open)
                # If we bought yesterday (or before), and exit_on_open is True, sell at Open today.
                if exit_on_open and pos['buy_date'] != date_str:
                    reason = "Market Open Exit"
                    sold = True
                    sell_price = row_open
                
                # B. Stop Loss / Take Profit (Intraday check approximation)
                # Note: If we already sold at Open, we don't check this.
                if not sold:
                    # check SL with Low
                    profit_rate_low = (row_low - pos['buy_price']) / pos['buy_price'] * 100
                    # check TP with High
                    profit_rate_high = (row_high - pos['buy_price']) / pos['buy_price'] * 100
                    
                    # Logic priority: SL usually triggers first if Gap down, but here we use Close for simplicity 
                    # unless we want high-precision tick simulation.
                    # Standard Engine uses Close to determine P/L, but let's be more precise if possible.
                    # For stability, we stick to Close for standard strategies, 
                    # but if Low hit SL, we might sell at SL price.
                    
                    # Simple Close-based Logic (Original)
                    current_profit_rate = (row_close - pos['buy_price']) / pos['buy_price'] * 100
                    
                    if current_profit_rate <= -abs(sl):
                        reason = "Stop Loss"
                        sold = True
                        # If Low was way below SL, we really executed at SL price (slippage ignored)
                        # But to be safe conservative, use Close or SL price.
                        # sell_price = row_close 
                    elif current_profit_rate >= tp:
                        reason = "Take Profit"
                        sold = True
                        # sell_price = row_close
                    
                    sell_price = row_close

                if sold:
                    sell_amount_raw = sell_price * pos['qty']
                    
                    # [Refined] Apply Sell Costs
                    # Sell Fee: 0.015% + Tax 0.20% (Standard 2024~2025) = 0.215%
                    # Note: Tax might change, using conservative 0.20%
                    SELL_COST_RATE = 0.00215
                    net_sell_amount = sell_amount_raw * (1 - SELL_COST_RATE)
                    
                    cash += net_sell_amount
                    
                    # Accurate Profit %: (Net Sell - Total Buy Cost) / Total Buy Cost
                    # Use stored buy_cost if available, else derive (backward compat)
                    buy_cost = pos.get('buy_cost', pos['buy_price'] * pos['qty'])
                    
                    real_profit_pct = ((net_sell_amount - buy_cost) / buy_cost) * 100
                    
                    trade = {
                        'code': code,
                        'buy_date': pos['buy_date'],
                        'sell_date': date_str,
                        'buy_price': pos['buy_price'],
                        'sell_price': sell_price,
                        'profit_pct': real_profit_pct,
                        'status': reason
                    }
                    trades.append(trade)
                    del holdings[code]

            # 2. Processing Requests (Buy)
            if cash > 0:
                # Iterate valid stocks
                for code in valid_stocks:
                    if code in holdings: continue
                    
                    df = processed_data.get(code)
                    if df is None: continue
                    
                    # Fast lookup existence
                    if date_str not in df.index: continue
                    
                    # Signal Check
                    has_signal = False
                    
                    if strategy_code:
                        try:
                            # Use .at for scalar lookup (Fastest)
                            # bool() conversion check
                            sig_val = df.at[date_str, 'signal']
                            has_signal = bool(sig_val)
                        except:
                            has_signal = False
                    else:
                        # Buy & Hold (Buy Once) logic
                         pass # Complex to track 'bought_once' without state. 
                         # For GA, we usually have a strategy. 
                         # If no strategy, GA is meaningless. 
                         # We ignore "Buy & Hold" logic for GA optimization context mostly, 
                         # OR we can assume simple buy on start.
                         # Let's support simple Start Buy:
                         if len(trades) == 0 and len(holdings) == 0:
                             # Just buy first available
                             has_signal = True
                    
                    if has_signal:
                        # [Look-ahead Bias Fix] Execute at Open
                        # Because signal was shifted (T-1), we execute at T Open.
                        buy_price = df.at[date_str, 'open']
                        
                        # Larry Williams Logic Support (Buy at Target Price)
                        if 'target_price' in df.columns:
                            target_p = df.at[date_str, 'target_price']
                            open_p = df.at[date_str, 'open']
                            if not pd.isna(target_p):
                                # If open is already higher than target (Gap Up), buy at open
                                buy_price = max(target_p, open_p)
                        
                        ratio = config.get('ratio', 10.0) / 100
                        invest_amt = cash * ratio
                        
                        # Min check
                        if invest_amt < buy_price: continue
                        
                        qty = int(invest_amt // buy_price)
                        
                        # [Refined] Apply Transaction Costs
                        # Buy Fee: 0.015% (Kiwoom standard)
                        # Sell Fee: 0.015% + Tax 0.20% = 0.215%
                        BUY_FEE = 0.00015
                        
                        if qty > 0:
                            cost = qty * buy_price
                            total_cost = cost * (1 + BUY_FEE)
                            
                            if cash >= total_cost:
                                cash -= total_cost
                                holdings[code] = {
                                    'qty': qty,
                                    'buy_price': buy_price, # Record raw price for stat
                                    'buy_cost': total_cost, # Record total cost for accurate PnL
                                    'buy_date': date_str
                                }

        # 3. Final Liquidate
        for code, pos in holdings.items():
            df = processed_data.get(code)
            if df is not None and not df.empty:
                last_price = df['close'].iloc[-1]
                cash += pos['qty'] * last_price
                
        # 4. Summary Calculation
        final_balance = cash
        total_profit = final_balance - initial_deposit
        return_pct = (total_profit / initial_deposit) * 100
        
        # Stats
        total_trades = len(trades)
        winning_trades = [t for t in trades if t['profit_pct'] > 0]
        losing_trades = [t for t in trades if t['profit_pct'] <= 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        # Average profit/loss
        avg_profit = sum(t['profit_pct'] for t in winning_trades) / win_count if win_count > 0 else 0
        avg_loss = sum(t['profit_pct'] for t in losing_trades) / loss_count if loss_count > 0 else 0
        avg_return = sum(t['profit_pct'] for t in trades) / total_trades if total_trades > 0 else 0
        
        # Max consecutive losses
        max_consecutive_loss = 0
        current_consecutive = 0
        for trade in trades:
            if trade['profit_pct'] <= 0:
                current_consecutive += 1
                max_consecutive_loss = max(max_consecutive_loss, current_consecutive)
            else:
                current_consecutive = 0

        summary = {
            'initial_deposit': initial_deposit,
            'final_cash': final_balance,
            'total_profit': total_profit,
            'return_pct': return_pct,
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'avg_return': avg_return,
            'max_consecutive_loss': max_consecutive_loss,
            'trades': trades
        }
        
        return summary
