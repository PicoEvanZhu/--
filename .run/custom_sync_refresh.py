import math
import os
import random
import subprocess
import sys
import tempfile
import time
from csv import DictReader
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pymysql
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path('/Users/zhutianyu/Documents/code/股票/backend')
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import models as _models  # noqa: F401
from app.models.stock_universe import StockUniverse
from app.services.stock_service import (
    _clean_us_name,
    _fetch_text_by_curl,
    _normalize_a_code,
    _normalize_hk_code,
    _normalize_us_symbol,
    _safe_float,
    _utc_now,
)


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}


def connect_mysql():
    return pymysql.connect(
        host='106.54.39.43',
        port=3306,
        user='stockapp',
        password='StockApp_20260307!R5m9',
        database='gupiao',
        charset='utf8mb4',
        autocommit=False,
        connect_timeout=15,
        read_timeout=300,
        write_timeout=300,
    )


engine = create_engine('mysql+pymysql://', creator=connect_mysql, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def request_json(url: str, params: Dict[str, Any], timeout: int = 40, retries: int = 5) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with requests.Session() as session:
                response = session.get(url, params=params, headers=HEADERS, timeout=timeout)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt < retries:
                sleep_seconds = min(10, attempt * 1.5) + random.uniform(0.2, 0.8)
                print(f'[sync] request retry {attempt}/{retries} for {url}: {exc}', flush=True)
                time.sleep(sleep_seconds)
    raise last_error or RuntimeError('request failed')


def fetch_a_rows() -> List[Dict[str, Any]]:
    print('[sync] fetching A-share from 东方财富 custom pagination...', flush=True)
    url = 'https://82.push2.eastmoney.com/api/qt/clist/get'
    params = {
        'pn': '1',
        'pz': '100',
        'po': '1',
        'np': '1',
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': '2',
        'invt': '2',
        'fid': 'f12',
        'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
        'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152',
    }
    first = request_json(url, params, timeout=40, retries=5)
    first_diff = ((first.get('data') or {}).get('diff')) or []
    total = int(((first.get('data') or {}).get('total')) or 0)
    per_page = max(1, len(first_diff))
    total_pages = math.ceil(total / per_page)
    print(f'[sync] A-share total={total} pages={total_pages}', flush=True)

    all_items: List[Dict[str, Any]] = list(first_diff)
    for page in range(2, total_pages + 1):
        params['pn'] = str(page)
        payload = request_json(url, params, timeout=40, retries=5)
        diff = ((payload.get('data') or {}).get('diff')) or []
        all_items.extend(diff)
        if page % 5 == 0 or page == total_pages:
            print(f'[sync] A-share page {page}/{total_pages} rows={len(all_items)}', flush=True)
        time.sleep(random.uniform(0.15, 0.45))

    rows: List[Dict[str, Any]] = []
    for item in all_items:
        normalized = _normalize_a_code(item.get('f12'))
        if normalized is None:
            continue
        symbol, code, market, board, exchange = normalized
        name = str(item.get('f14') or '').strip()
        if not name:
            continue
        rows.append(
            {
                'symbol': symbol,
                'code': code,
                'name': name,
                'market': market,
                'board': board,
                'exchange': exchange,
                'source': 'eastmoney_clist',
                'price': _safe_float(item.get('f2')),
                'change_pct': _safe_float(item.get('f3')),
                'volume': _safe_float(item.get('f5')),
                'turnover': _safe_float(item.get('f6')),
            }
        )
    print(f'[sync] A-share rows={len(rows)}', flush=True)
    return rows


def fetch_hk_rows() -> List[Dict[str, Any]]:
    print('[sync] fetching HK list from HKEX...', flush=True)
    url = 'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=True) as file:
        subprocess.run(['curl', '-fsSL', '--max-time', '90', '-o', file.name, url], check=True, capture_output=True, text=True)
        df = pd.read_excel(file.name, header=2)

    rows: List[Dict[str, Any]] = []
    for item in df.to_dict('records'):
        category = str(item.get('Category') or '').strip().lower()
        if category != 'equity':
            continue
        code = _normalize_hk_code(item.get('Stock Code'))
        if code is None:
            continue
        name = str(item.get('Name of Securities') or '').strip()
        if not name:
            continue
        rows.append(
            {
                'symbol': f'{code}.HK',
                'code': code,
                'name': name,
                'market': '港股',
                'board': '港股',
                'exchange': 'HKEX',
                'source': 'hkex_list_of_securities',
                'price': None,
                'change_pct': None,
                'volume': None,
                'turnover': None,
            }
        )
    print(f'[sync] HK rows={len(rows)}', flush=True)
    return rows


def fetch_us_rows() -> List[Dict[str, Any]]:
    print('[sync] fetching US list from nasdaqtrader...', flush=True)
    nasdaq_text = _fetch_text_by_curl('https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt')
    other_text = _fetch_text_by_curl('https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt')
    exchange_map = {'N': 'NYSE', 'A': 'NYSEMKT', 'P': 'NYSEARCA', 'Z': 'BATS', 'V': 'IEX'}
    merged: Dict[str, Dict[str, Any]] = {}

    for item in DictReader(StringIO(nasdaq_text), delimiter='|'):
        code = _normalize_us_symbol(item.get('Symbol'))
        if code is None or code == 'FILECREATIONTIME':
            continue
        if str(item.get('Test Issue') or '').strip().upper() == 'Y':
            continue
        if str(item.get('ETF') or '').strip().upper() == 'Y':
            continue
        name = _clean_us_name(item.get('Security Name'))
        if not name:
            continue
        merged[f'{code}.US'] = {
            'symbol': f'{code}.US',
            'code': code,
            'name': name,
            'market': '美股',
            'board': '美股',
            'exchange': 'NASDAQ',
            'source': 'nasdaqtrader_nasdaqlisted',
            'price': None,
            'change_pct': None,
            'volume': None,
            'turnover': None,
        }

    for item in DictReader(StringIO(other_text), delimiter='|'):
        code = _normalize_us_symbol(item.get('ACT Symbol'))
        if code is None or code == 'FILECREATIONTIME':
            continue
        if str(item.get('Test Issue') or '').strip().upper() == 'Y':
            continue
        if str(item.get('ETF') or '').strip().upper() == 'Y':
            continue
        name = _clean_us_name(item.get('Security Name'))
        if not name:
            continue
        exchange = exchange_map.get(str(item.get('Exchange') or '').strip().upper(), 'US')
        merged[f'{code}.US'] = {
            'symbol': f'{code}.US',
            'code': code,
            'name': name,
            'market': '美股',
            'board': '美股',
            'exchange': exchange,
            'source': 'nasdaqtrader_otherlisted',
            'price': None,
            'change_pct': None,
            'volume': None,
            'turnover': None,
        }

    rows = sorted(merged.values(), key=lambda row: row['symbol'])
    print(f'[sync] US rows={len(rows)}', flush=True)
    return rows


def main() -> int:
    db = SessionLocal()
    try:
        existing = {row.symbol: row for row in db.query(StockUniverse).all()}
        print(f'[sync] existing rows={len(existing)}', flush=True)

        merged: Dict[str, Dict[str, Any]] = {}
        for row in fetch_a_rows():
            merged[row['symbol']] = row
        for row in fetch_hk_rows():
            merged[row['symbol']] = row
        for row in fetch_us_rows():
            merged[row['symbol']] = row

        now = _utc_now()
        objects: List[StockUniverse] = []
        for row in sorted(merged.values(), key=lambda item: item['symbol']):
            old = existing.get(row['symbol'])
            price = row['price'] if row['price'] is not None else (float(old.price) if old and old.price is not None else None)
            change_pct = row['change_pct'] if row['change_pct'] is not None else (float(old.change_pct) if old and old.change_pct is not None else None)
            volume = row['volume'] if row['volume'] is not None else (float(old.volume) if old and old.volume is not None else None)
            turnover = row['turnover'] if row['turnover'] is not None else (float(old.turnover) if old and old.turnover is not None else None)
            objects.append(
                StockUniverse(
                    symbol=row['symbol'],
                    code=row['code'],
                    name=row['name'],
                    market=row['market'],
                    board=row['board'],
                    exchange=row['exchange'],
                    source=row['source'],
                    listed=True,
                    price=price,
                    change_pct=change_pct,
                    volume=volume,
                    turnover=turnover,
                    updated_at=now,
                )
            )

        print(f'[sync] writing rows={len(objects)}', flush=True)
        db.query(StockUniverse).delete(synchronize_session=False)
        db.bulk_save_objects(objects)
        db.commit()
        counts: Dict[str, int] = {}
        for item in objects:
            counts[item.market] = counts.get(item.market, 0) + 1
        print('[sync] done', counts, flush=True)
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
