import streamlit as st
import sqlite3
import pandas as pd
import gspread
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import run_flow
import os

# ==========================================
# 1. 設定エリア（ここを自分の環境に合わせて書き換える）
# ==========================================
JSON_FILE = 'client_secret.json'
STORAGE_FILE = 'credentials_storage.json'
SPREADSHEET_ID = '1keU0bp0xhlohxptLLLddEXQfKJEWc8F2ubSDJcNbWZY' # URLから取得したID

# スプシの列設定（名前はスプシの1行目と完全一致させる）
COL_TIMESTAMP = 'タイムスタンプ'
COL_NAME = '名前を入力してください'
COL_AMOUNT = '使用金額'
STATUS_COLUMN_INDEX = 7 # 「承認ステータス」が左から何列目か(G列なら7)

# ==========================================
# 2. 認証・Google連携機能
# ==========================================
def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    storage = Storage(STORAGE_FILE)
    creds = storage.get()
    if not creds or creds.invalid:
        flow = flow_from_clientsecrets(JSON_FILE, scope=scope)
        creds = run_flow(flow, storage)
    return gspread.authorize(creds)

# ==========================================
# 3. データベース（SQLite）操作機能
# ==========================================
def init_db():
    conn = sqlite3.connect('finance_data.db')
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            name TEXT,
            amount INTEGER,
            status TEXT DEFAULT '未処理'
        )
    ''')
    conn.commit()
    return conn

def sync_from_google():
    """スプシのデータをSQLiteに取り込む"""
    client = get_gspread_client()
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    data = sheet.get_all_records()
    
    conn = init_db()
    cursor = conn.cursor()
    for row in data:
        # 重複チェック（タイムスタンプと名前で判定）
        cursor.execute('SELECT * FROM requests WHERE timestamp=? AND name=?', (str(row[COL_TIMESTAMP]), row[COL_NAME]))
        if cursor.fetchone() is None:
            cursor.execute('INSERT INTO requests (timestamp, name, amount, status) VALUES (?, ?, ?, ?)',
                           (str(row[COL_TIMESTAMP]), row[COL_NAME], row[COL_AMOUNT], '未処理'))
    conn.commit()
    conn.close()

def update_decision(row_id, timestamp, new_status):
    """SQLiteとスプシの両方を更新する"""
    # SQLite更新
    conn = sqlite3.connect('finance_data.db')
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status = ? WHERE id = ?", (new_status, row_id))
    conn.commit()
    conn.close()

    # スプシ更新
    client = get_gspread_client()
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    try:
        cell = sheet.find(timestamp)
        sheet.update_cell(cell.row, STATUS_COLUMN_INDEX, new_status)
    except Exception as e:
        st.error(f"スプシの更新に失敗しました: {e}")

# ==========================================
# 4. Streamlit 画面表示
# ==========================================
st.set_page_config(page_title="部費承認アプリ", layout="centered")
st.title("💰 部費申請・承認管理")

# 同期ボタン
if st.sidebar.button("🔄 スプシから最新データを取り込む"):
    with st.spinner("同期中..."):
        sync_from_google()
        st.success("同期完了！")

# データの読み込み
conn = init_db()
df = pd.read_sql_query("SELECT * FROM requests", conn)
conn.close()

# メイン表示
tab1, tab2 = st.tabs(["未処理の申請", "処理済み履歴"])

with tab1:
    unprocessed = df[df['status'] == '未処理']
    if unprocessed.empty:
        st.info("現在、未処理の申請はありません。")
    else:
        for _, row in unprocessed.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                c1.write(f"**{row['name']}**\n\n{row['timestamp']}")
                c2.write(f"### ¥{row['amount']:,}")
                if c3.button("✅", key=f"y_{row['id']}"):
                    update_decision(row['id'], row['timestamp'], "承認")
                    st.rerun()
                if c4.button("❌", key=f"n_{row['id']}"):
                    update_decision(row['id'], row['timestamp'], "非承認")
                    st.rerun()
                st.divider()

with tab2:
    st.dataframe(df[df['status'] != '未処理'], use_container_width=True)