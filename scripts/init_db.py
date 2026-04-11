"""
数据库初始化脚本

用法：
    python scripts/init_db.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_db, engine
from sqlalchemy import text

def main():
    print("初始化数据库...")
    init_db()

    # 验证表创建
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
        print(f"已创建 {len(tables)} 张表:")
        for t in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {t[0]}")).fetchone()[0]
            print(f"  - {t[0]} ({count} 条记录)")

    print("\n数据库初始化完成！")
    print(f"数据库文件: {engine.url}")

if __name__ == "__main__":
    main()
