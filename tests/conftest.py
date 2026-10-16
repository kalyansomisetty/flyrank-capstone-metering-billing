import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine]:
    database_url = os.environ.get("TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests.")

    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+psycopg driver.")

    database_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if database_name != "flyrank_test":
        pytest.fail("Integration tests may only connect to flyrank_test.")

    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            current_database = connection.execute(text("SELECT current_database()")).scalar_one()

        if current_database != "flyrank_test":
            pytest.fail("Connected database is not flyrank_test.")

        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session]:
    connection = test_engine.connect()
    transaction = connection.begin()
    test_session = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
    )()

    try:
        yield test_session
    finally:
        test_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
