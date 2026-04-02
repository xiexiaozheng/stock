"""
首次全量数据采集脚本

用法：
    cd lixinger-local
    # 采集全量数据（耗时较长）
    python scripts/first_collect.py

    # 只采集指定股票（测试用）
    python scripts/first_collect.py --codes 000001 600519 300750
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_db, SessionLocal
from collectors.scheduler import DataCollector
from utils.logger import setup_logging

setup_logging()


def main():
    parser = argparse.ArgumentParser(description="首次全量数据采集")
    parser.add_argument("--codes", nargs="*", help="指定股票代码（不填则采集全市场）")
    args = parser.parse_args()

    print("初始化数据库...")
    init_db()

    db = SessionLocal()
    try:
        collector = DataCollector(db)
        print(f"开始全量采集{'（指定股票: ' + ', '.join(args.codes) + '）' if args.codes else '（全市场）'}...")
        collector.run_full_refresh(stock_codes=args.codes)
        print("采集完成！")
    finally:
        db.close()


if __name__ == "__main__":
    main()
