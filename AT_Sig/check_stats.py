import os
import sys
from acc_val import fn_kt00004
from login import fn_au10001

sys.path.append('d:/AG/KW_AutoTrading')
token = fn_au10001()
data = fn_kt00004(token=token)

d2 = data.get('d2_entra', '0')
tot_pur = data.get('tot_pur_amt', '0')
asset = data.get('aset_evlt_amt', '0')
sunik = data.get('lspft_amt', '0')

print(f"D2_Withdrawal: {d2}")
print(f"Total Purchase: {tot_pur}")
print(f"Asset Evaluation: {asset}")
print(f"P/L: {sunik}")
