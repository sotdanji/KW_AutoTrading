import os
log_path = r'd:\AG\KW_AutoTrading\AT_Sig\at_sig_direct_debug.log'
out_path = r'd:\AG\KW_AutoTrading\AT_Sig\at_sig_direct_debug_utf8.log'
if os.path.exists(log_path):
    with open(log_path, 'r', encoding='utf-16') as f:
        content = f.read()
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(content)
