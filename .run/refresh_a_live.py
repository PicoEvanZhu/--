import math
import random
import time
import pymysql
import requests
from pathlib import Path
import os, sys

ROOT = Path('/Users/zhutianyu/Documents/code/股票/backend')
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.stock_service import _normalize_a_code, _safe_float, _utc_now

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}


def request_json(url, params, timeout=40, retries=8):
    last = None
    for attempt in range(1, retries + 1):
        try:
            with requests.Session() as s:
                r = s.get(url, params=params, headers=HEADERS, timeout=timeout)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            last = exc
            print(f'[a-refresh] retry {attempt}/{retries}: {exc}', flush=True)
            time.sleep(min(15, attempt * 2) + random.uniform(0.2, 0.8))
    raise last


def main():
    url = 'https://82.push2.eastmoney.com/api/qt/clist/get'
    params = {
        'pn': '1', 'pz': '100', 'po': '1', 'np': '1', 'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': '2', 'invt': '2', 'fid': 'f12',
        'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
        'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152',
    }
    first = request_json(url, params)
    first_diff = ((first.get('data') or {}).get('diff')) or []
    total = int(((first.get('data') or {}).get('total')) or 0)
    total_pages = math.ceil(total / max(1, len(first_diff)))
    print(f'[a-refresh] total={total} pages={total_pages}', flush=True)
    all_items = list(first_diff)
    for page in range(2, total_pages + 1):
        params['pn'] = str(page)
        payload = request_json(url, params)
        all_items.extend(((payload.get('data') or {}).get('diff')) or [])
        if page % 5 == 0 or page == total_pages:
            print(f'[a-refresh] page {page}/{total_pages} rows={len(all_items)}', flush=True)
        time.sleep(random.uniform(0.15, 0.45))

    rows = []
    now = _utc_now()
    for item in all_items:
        normalized = _normalize_a_code(item.get('f12'))
        if normalized is None:
            continue
        symbol, code, market, board, exchange = normalized
        name = str(item.get('f14') or '').strip()
        if not name:
            continue
        rows.append((symbol, code, name, market, board, exchange, 'eastmoney_clist', 1, _safe_float(item.get('f2')), _safe_float(item.get('f3')), _safe_float(item.get('f5')), _safe_float(item.get('f6')), now))
    print(f'[a-refresh] normalized_rows={len(rows)}', flush=True)

    conn = pymysql.connect(host='106.54.39.43', port=3306, user='stockapp', password='StockApp_20260307!R5m9', database='gupiao', charset='utf8mb4', autocommit=False, connect_timeout=15, read_timeout=300, write_timeout=300)
    try:
        sql = (
            'INSERT INTO stock_universe (symbol, code, name, market, board, exchange, source, listed, price, change_pct, volume, turnover, updated_at) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
            'ON DUPLICATE KEY UPDATE code=VALUES(code), name=VALUES(name), market=VALUES(market), board=VALUES(board), exchange=VALUES(exchange), source=VALUES(source), listed=VALUES(listed), price=VALUES(price), change_pct=VALUES(change_pct), volume=VALUES(volume), turnover=VALUES(turnover), updated_at=VALUES(updated_at)'
        )
        with conn.cursor() as cur:
            for start in range(0, len(rows), 100):
                batch = rows[start:start+100]
                cur.executemany(sql, batch)
                conn.commit()
                if (start + len(batch)) % 1000 == 0 or (start + len(batch)) == len(rows):
                    print(f'[a-refresh] upserted={start + len(batch)}', flush=True)
        print('[a-refresh] done', flush=True)
    finally:
        conn.close()

if __name__ == '__main__':
    main()
