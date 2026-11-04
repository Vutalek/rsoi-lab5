from uuid import UUID
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from orm import TicketORM


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

with patch("utils.construct_engine", return_value=test_engine):
    import app


@pytest.fixture(autouse=True)
def database():
    TicketORM.metadata.create_all(bind=test_engine)

    with Session(test_engine) as session:
        session.add_all([
            TicketORM(
                id=1,
                ticket_uid=UUID("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
                username="vuta",
                flight_number="AFL031",
                price=1500,
                status="PAID"
            ),
            TicketORM(
                id=2,
                ticket_uid=UUID("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
                username="vuta2",
                flight_number="LFA130",
                price=2000,
                status="CANCELED"
            )
        ])
        session.commit()

    yield

    TicketORM.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.app.dependency_overrides, app.authenticate, lambda: "vuta")
    with TestClient(app.app) as test_client:
        yield test_client
