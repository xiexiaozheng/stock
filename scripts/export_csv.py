"""
数据导出脚本

用法：
    python scripts/export_csv.py --table stocks --output data/export/stocks.csv
    python scripts/export_csv.py --table financials --code 000001
    python scripts/export_csv.py --table valuations --code 600519 --output data/export/moutai_val.csv
"""
import sys
import os
import argparse
import csv
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import engine
from sqlalchemy import text


ALLOWED_TABLES = [
    "stocks", "daily_quotes", "financials", "valuations", "dividends", "watchlist",
    "stock_basic", "daily_market_valuation", "quarterly_finance",
]


def export_table(table: str, code: str = None, output: str = None):
    if table not in ALLOWED_TABLES:
        print(f"不支持的表: {table}，可选: {ALLOWED_TABLES}")
        sys.exit(1)

    query = f"SELECT * FROM {table}"
    params = {}
    if code and table not in ("stocks", "stock_basic"):
        # 新核心表使用 ts_code 而非 stock_code
        if table in ("daily_market_valuation", "quarterly_finance"):
            query += " WHERE ts_code = :code"
        else:
            query += " WHERE stock_code = :code"
        params["code"] = code

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = result.fetchall()
        columns = list(result.keys())

    if not rows:
        print(f"表 {table} 中没有数据" + (f"（股票: {code}）" if code else ""))
        return

    if output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{code}" if code else ""
        os.makedirs("data/export", exist_ok=True)
        output = f"data/export/{table}{suffix}_{ts}.csv"

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"已导出 {len(rows)} 条记录到: {output}")


def main():
    parser = argparse.ArgumentParser(description="数据导出工具")
    parser.add_argument("--table", required=True, choices=ALLOWED_TABLES, help="要导出的表名")
    parser.add_argument("--code", help="股票代码（可选，只导出该股票数据）")
    parser.add_argument("--output", help="输出文件路径（默认自动生成）")
    args = parser.parse_args()

    export_table(args.table, args.code, args.output)


if __name__ == "__main__":
    main()
