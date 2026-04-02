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


def init_db():
    """初始化数据库，创建所有表"""
    from models.stock import Stock, DailyQuote, Watchlist
    from models.financial import Financial
    from models.valuation import Valuation, Dividend
    from models.screener import Screener, Industry, IndustryMember

    Base.metadata.create_all(bind=engine)

    # 创建索引（如果不存在）
    with engine.connect() as conn:
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_daily_quotes_stock_date ON daily_quotes(stock_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_financials_stock_date ON financials(stock_code, report_date)",
            "CREATE INDEX IF NOT EXISTS idx_valuations_stock_date ON valuations(stock_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(stock_code)",
            "CREATE INDEX IF NOT EXISTS idx_dividends_stock ON dividends(stock_code)",
        ]
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
        conn.commit()

    logger.info("数据库初始化完成")
