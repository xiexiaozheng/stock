"""数据库连接与初始化"""
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from config import DATABASE_URL, BASE_DIR

logger = logging.getLogger(__name__)

# 确保数据目录存在
Path(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

# 启用 SQLite WAL 模式（提升并发性能）
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_daily_quotes_unique_constraint(conn):
    """
    为已存在的 daily_quotes 表迁移加联合唯一约束 (stock_code, trade_date)。

    SQLite 不支持 ALTER TABLE ADD CONSTRAINT，因此通过以下步骤安全迁移：
    1. 检查唯一约束是否已存在（通过 PRAGMA index_list 检查是否有 unique index）
    2. 若不存在：去除重复行（保留每组最新 id）→ 新建带约束的临时表 →
       迁移数据 → 删除旧表 → 重命名。
    """
    # 检查 daily_quotes 表是否存在
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_quotes'")
    ).fetchone()
    if result is None:
        return  # 表不存在，create_all 之后会带正确约束创建

    # 检查是否已有 (stock_code, trade_date) 的 unique index
    indexes = conn.execute(text("PRAGMA index_list('daily_quotes')")).fetchall()
    for idx in indexes:
        idx_name = idx[1]
        idx_unique = idx[2]
        if not idx_unique:
            continue
        # 检查该唯一索引是否覆盖 (stock_code, trade_date)
        idx_info = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
        cols = {row[2] for row in idx_info}
        if cols == {"stock_code", "trade_date"}:
            logger.debug("daily_quotes 已有 (stock_code, trade_date) 唯一约束，无需迁移")
            return

    logger.info("daily_quotes 缺少 (stock_code, trade_date) 唯一约束，开始安全迁移...")

    # 关闭 foreign key 约束以便迁移
    conn.execute(text("PRAGMA foreign_keys=OFF"))

    try:
        # 1. 删除重复行（每组 (stock_code, trade_date) 只保留最大 id 的行）
        conn.execute(text("""
            DELETE FROM daily_quotes
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM daily_quotes
                GROUP BY stock_code, trade_date
            )
        """))
        logger.info("已清理 daily_quotes 重复行")

        # 2. 获取当前表的列定义，用于重建
        table_info = conn.execute(text("PRAGMA table_info('daily_quotes')")).fetchall()
        col_names = [row[1] for row in table_info]

        # 3. 新建带唯一约束的临时表
        conn.execute(text("""
            CREATE TABLE daily_quotes_new (
                id INTEGER PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL REFERENCES stocks(stock_code),
                trade_date DATE NOT NULL,
                open NUMERIC(10, 2),
                high NUMERIC(10, 2),
                low NUMERIC(10, 2),
                close NUMERIC(10, 2),
                volume BIGINT,
                amount NUMERIC(20, 2),
                turnover_rate NUMERIC(8, 4),
                amplitude NUMERIC(8, 4),
                UNIQUE (stock_code, trade_date)
            )
        """))

        # 4. 迁移数据（只迁移新表中存在的列）
        new_table_info = conn.execute(text("PRAGMA table_info('daily_quotes_new')")).fetchall()
        new_col_names = [row[1] for row in new_table_info]
        common_cols = [c for c in col_names if c in new_col_names]
        common_cols_csv = ", ".join(common_cols)
        conn.execute(text(f"""
            INSERT INTO daily_quotes_new ({common_cols_csv})
            SELECT {common_cols_csv} FROM daily_quotes
        """))
        logger.info("已将数据迁移到 daily_quotes_new")

        # 5. 替换旧表
        conn.execute(text("DROP TABLE daily_quotes"))
        conn.execute(text("ALTER TABLE daily_quotes_new RENAME TO daily_quotes"))
        logger.info("daily_quotes 迁移完成，已加唯一约束 (stock_code, trade_date)")

    finally:
        conn.execute(text("PRAGMA foreign_keys=ON"))


def init_db():
    """初始化数据库，创建所有表"""
    # 旧表模型（保持向后兼容）
    from models.stock import Stock, DailyQuote, Watchlist
    from models.financial import Financial
    from models.valuation import Valuation, Dividend
    from models.screener import Screener, Industry, IndustryMember
    # 新核心表模型
    from models.core import StockBasic, DailyMarketValuation, QuarterlyFinance

    # 对已有 SQLite 数据库执行必要的 schema 迁移（在 create_all 之前）
    if "sqlite" in DATABASE_URL:
        with engine.begin() as conn:
            _migrate_daily_quotes_unique_constraint(conn)

    Base.metadata.create_all(bind=engine)

    # 创建索引（如果不存在）
    with engine.connect() as conn:
        indexes = [
            # 旧表索引（普通索引，唯一约束已在 ORM __table_args__ 中声明）
            "CREATE INDEX IF NOT EXISTS idx_daily_quotes_stock_date ON daily_quotes(stock_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_financials_stock_date ON financials(stock_code, report_date)",
            "CREATE INDEX IF NOT EXISTS idx_valuations_stock_date ON valuations(stock_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(stock_code)",
            "CREATE INDEX IF NOT EXISTS idx_dividends_stock ON dividends(stock_code)",
            # 新核心表索引（联合索引已在 __table_args__ 中声明，此处补充单列索引）
            "CREATE INDEX IF NOT EXISTS idx_stock_basic_industry ON stock_basic(industry)",
            "CREATE INDEX IF NOT EXISTS idx_dmv_ts_code ON daily_market_valuation(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_qf_ts_code ON quarterly_finance(ts_code)",
        ]
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
        conn.commit()

    logger.info("数据库初始化完成")
