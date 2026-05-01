# BackTester - Sotdanji Backtesting Lab

A **high-performance stock backtesting and strategy optimization tool** utilizing the Kiwoom Securities REST API.
It automatically converts user-written Kiwoom formulas into Python code to verify the validity of trading strategies based on historical data.

> ⚠️ **Caution**: As this program is **not for actual trading**, it is configured to automatically connect to Kiwoom's **Real Account Mode**. (Historical chart data retrieval may not be smooth with the Mock Investment API)

## Key Features

### 1. 📊 Powerful Backtesting Engine
- **Formula Conversion**: Automatically converts Kiwoom formulas (e.g., `CrossUp(C, avg(C, 20))`) into Python code.
- **Universe Mode**: Supports verification across all stocks.
- **Real-time Logs**: Provides immediate visual feedback (Buy/Sell, Return %) when trades occur.

### 2. 🧬 GA Optimization (Genetic Algorithm)
- **Genetic Algorithm**: Automatically searches for parameters (moving average period, SL/TP ratios, etc.) that yield the highest returns.
- **Smart Search**: Derives optimal values using evolutionary techniques rather than random substitution.
- **Parallel Processing**: Supports high-speed operation utilizing multi-cores (approx. 4.7x speed improvement)

### 3. 🛡️ Safety & Reliability
- **Syntax Check**: Automatically detects Python syntax errors before execution.
- **Data Backup**: Automatic backup function for important data and source code.
- **Fail-Safe**: Safely terminates and recovers even in case of API errors or network disconnection.

### 4. 🎨 User-Friendly UI
- **Dark Theme**: Modern design comfortable for the eyes even during long analysis sessions.
- **Intuitive Settings**: Start testing with just a few clicks without complex configurations.
- **Detailed Report**: Provides professional analysis metrics such as Win Rate, Profit/Loss Ratio, Max Drawdown (MDD), etc.

---

## System Requirements

- **OS**: Windows 10/11 (Recommended)
- **Python**: 3.8 or higher (3.9~3.11 Recommended)
- **API**: Internet connection required (Uses Kiwoom Securities REST API)

---

## Installation & Execution

### 1. Installation
Run the following command in the terminal (PowerShell) to install required packages.

```powershell
cd d:\AG\KW_AutoTrading\BackTester
pip install -r requirements.txt
```

### 2. Check Settings
Check if `settings.json` exists, and if necessary, copy `settings.template.json` to create it.

```powershell
copy settings.template.json settings.json
```

### 3. Run Program
```powershell
python main.py
```

---

## 🚀 Usage Guide

### Step 1: Establish Strategy & Convert
1. Click the **[📋 Strategy Setup]** tab in the center of the program.
2. Enter your desired strategy formula in the **'Kiwoom Formula Input'** field.
   - Example: `CrossUp(C, avg(C, 20))` (20-day Moving Average Golden Cross)
3. Click the **[🔄 Convert to Python]** button to automatically convert the formula into Python code.
4. Check if the code has been generated in the **'Converted Python Code'** field at the bottom.
   - You can manually edit the converted code if necessary.
5. Click the **[✅ Verify Code]** button to check for syntax errors.
6. **[💾 Save]** the strategy to reuse it later. Restore it with **[📂 Load]** when needed.

### Step 2: Backtest Settings (Left Panel)
1. **Stock Selection**:
   - **All Stocks (Universe)**: Leave the input field **empty** to test against all stocks.
     *(⚠️ To prevent API call limits, basically top **200 stocks** are sampled)*
   - **Single Stock**: Enter the code if you want to verify a specific stock (e.g., `005930`).
2. **Condition Settings**:
   - **Backtest Period**: Specify the start and end dates.
   - **Stock Filter**: Filter targets by setting minimum transaction amount and volume conditions.
   - **Real Trading Capital**: Set initial deposit and investment ratio per stock.
   - **Risk Management**: Set Take Profit (TP) and Stop Loss (SL) percentages.

### Step 3: Run Backtest & Analyze
1. Click the **[Run Backtest]** button on the left. *(Enabled only when logged in)*
2. Check the progress in real-time in the **[Execution Log]** panel on the right.
3. Upon completion, the **[📊 Performance Summary]** tab opens automatically.
   - Visually check **Return, Win Rate, Cumulative Return Chart**, etc.
4. In the **[💼 Trade History]** tab, you can view detailed daily trading records like Excel.

### 💡 Tip: Strategy Optimization (GA)
Clicking the **[Genetic Algorithm Optimization]** button lets AI automatically optimize key strategy parameters.
*(This button works only in **Universe Mode**, so please ensure the stock selection field is empty)*

1. **Set Search Range**:
   - **Stop Loss (SL)**: Min~Max range (e.g., 1.0% ~ 10.0%)
   - **Take Profit (TP)**: Min~Max range (e.g., 5.0% ~ 30.0%)
   - **Ratio**: Investment ratio range per stock (e.g., 10% ~ 50%)
2. **GA Engine Settings**:
   - **Population**: Number of strategies to test per generation (Recommended: 10~20)
   - **Generations**: Number of evolutions (Recommended: 5~10)
3. Click **[Start]** to proceed with optimization; the highest return is updated in real-time.
4. After completion, click **[Apply Result]** to automatically input the best parameters into the main screen.
5. Click the **[Run Backtest]** button to evaluate the strategy recommended by GA.

---

## Dev Info

### Tech Stack
- **Language**: Python 3.9+
- **GUI Framework**: PyQt6
- **Data Analysis**: Pandas, NumPy
- **Algorithm**: Genetic Algorithm (Custom Implementation)

### Directory Structure
- `core/`: Core logic including Backtesting Engine, Formula Parser, GA Optimizer
- `ui/`: PyQt6-based User Interface
- `strategies/`: Saved strategy files
- `logs/`: Execution log repository
- `tests/`: Unit tests and performance profiling scripts

---

## License
This program was created for personal research and study purposes.
Consent from the developer is required for commercial use.

**Version**: 1.2.0 (Stable Release)
**Last Updated**: 2026-01-27 (Optimized)
