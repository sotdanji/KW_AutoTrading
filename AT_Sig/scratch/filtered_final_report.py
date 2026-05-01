import json
import os
import sys

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
report_path = os.path.join(project_root, "AT_Sig", "scratch", "rebuilt_report.json")

def print_filtered_report():
    if not os.path.exists(report_path):
        print("Report not found.")
        return
    
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Filter: Price >= 5000
    filtered = [r for r in data if r['close'] >= 5000]
    filtered.sort(key=lambda x: x['ratio'], reverse=True)
    
    print("\n[전략 포착 종목 리스트 - 4/10 (5,000원 이상 필터 적용)]")
    print("-" * 75)
    for r in filtered:
        print(f"[{r['code']}] {r['name']:<15} | TL: {r['tl']:>8,.0f} | 종가: {r['close']:>8,.0f} | 돌파율: {r['ratio']:>6.2f}%")
    print("=" * 75)
    print(f"* 제외된 저가주: {len(data) - len(filtered)}개")

if __name__ == "__main__":
    print_filtered_report()
