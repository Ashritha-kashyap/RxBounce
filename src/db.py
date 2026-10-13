"""Database helpers (MySQL via SQLAlchemy + PyMySQL)."""
import re
import pandas as pd
from sqlalchemy import create_engine, text
import config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)
    return _engine


def is_mysql():
    return get_engine().dialect.name == "mysql"


def run_sql_file(path):
    """Execute a .sql file statement by statement (comments stripped)."""
    sql = open(path, encoding="utf-8").read()
    sql = re.sub(r"--.*?$", "", sql, flags=re.M)
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with get_engine().begin() as con:
        for s in statements:
            con.exec_driver_sql(s.replace("%", "%%"))   # PyMySQL treats % as a placeholder


def query(sql, params=None):
    with get_engine().connect() as con:
        return pd.read_sql(text(sql), con, params=params or {})


def execute(sql, params=None):
    with get_engine().begin() as con:
        return con.execute(text(sql), params or {})
