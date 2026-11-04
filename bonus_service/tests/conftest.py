from uuid import UUID
from datetime import datetime as dtime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from orm import PrivilegeORM, PrivilegeHistoryORM


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

with patch("utils.construct_engine", return_value=test_engine):
    import app


@pytest.fixture(autouse=True)
def database():
    PrivilegeORM.metadata.create_all(bind=test_engine)
    PrivilegeHistoryORM.metadata.create_all(bind=test_engine)

    with Session(test_engine) as session:
        session.add_all([
            PrivilegeORM(
                id=1,
                username="vuta",
                status="GOLD",
                balance=1500
            ),
            PrivilegeORM(
                id=2,
                username="vuta2",
                status="BRONZE",
                balance=2000
            ),
            PrivilegeHistoryORM(
                id=1,
                privilege_id=1,
                ticket_uid=UUID("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
                datetime=dtime.fromisoformat("2026-10-10 20:00:00"),
                balance_diff=1500,
                operation_type="FILL_IN_BALANCE"
            ),
            PrivilegeHistoryORM(
                id=2,
                privilege_id=1,
                ticket_uid=UUID("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
                datetime=dtime.fromisoformat("2026-10-10 20:00:00"),
                balance_diff=1500,
                operation_type="FILL_IN_BALANCE"
            ),
            PrivilegeHistoryORM(
                id=3,
                privilege_id=2,
                ticket_uid=UUID("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
                datetime=dtime.fromisoformat("2026-10-10 20:00:00"),
                balance_diff=1500,
                operation_type="FILL_IN_BALANCE"
            )
        ])
        session.commit()

    yield

    PrivilegeORM.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.app.dependency_overrides, app.authenticate, lambda: "vuta")
    with TestClient(app.app) as test_client:
        yield test_client
