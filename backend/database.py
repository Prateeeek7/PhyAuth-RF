import logging

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

import config

logger = logging.getLogger("database")

engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})


def _migrate(eng) -> None:
    """Add columns introduced after a table was first created (SQLite has no
    automatic schema evolution and create_all() never alters tables)."""
    insp = inspect(eng)
    for table in SQLModel.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl_type = col.type.compile(dialect=eng.dialect)
            default = ""
            if col.default is not None and getattr(col.default, "is_scalar", False):
                v = col.default.arg
                default = f" DEFAULT {int(v) if isinstance(v, bool) else repr(v)}"
            with eng.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}{default}'))
            logger.info("migrated: added %s.%s", table.name, col.name)


def init_db(eng=None) -> None:
    import backend.db_models  # noqa: F401  (registers tables)
    eng = eng or engine
    SQLModel.metadata.create_all(eng)
    _migrate(eng)


def get_session():
    with Session(engine) as session:
        yield session
