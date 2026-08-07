from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


# prepare_threshold=None disables psycopg3's automatic server-side prepared statements.
# Supabase's Connection Pooling (Transaction mode, port 6543) can route different
# transactions on the same client connection to different physical backend connections,
# so psycopg's local bookkeeping of "already prepared statement _pg3_N here" can go stale
# and collide (DuplicatePreparedStatement) -- this is a documented incompatibility between
# psycopg3 and PgBouncer transaction-mode pooling, not specific to any one query.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_database() -> bool:
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return True
