
import sqlite3
import os

db_path = r'd:\AG\KW_AutoTrading\data\state.db'
if not os.path.exists(db_path):
    print("DB file not found")
else:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM stock_state WHERE stk_cd = ?", ('330860',))
    row = cursor.fetchone()
    if row:
        print(dict(row))
    else:
        print("No state found for 100090")
    conn.close()
