from datetime import datetime as dtime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from orm import FlightORM, AirportORM


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

with patch("utils.construct_engine", return_value=test_engine):
    import app


@pytest.fixture(autouse=True)
def database():
    AirportORM.metadata.create_all(bind=test_engine)
    FlightORM.metadata.create_all(bind=test_engine)

    with Session(test_engine) as session:
        session.add_all([
            AirportORM(
                id=1,
                name="Шереметьево",
                city="Москва",
                country="Россия"
            ),
            AirportORM(
                id=2,
                name="Пулково",
                city="Санкт-Петербург",
                country="Россия"
            ),
            FlightORM(
                id=1,
                flight_number="AFL031",
                datetime=dtime.fromisoformat("2026-10-08 20:00"),
                from_airport_id=2,
                to_airport_id=1,
                price=1500
            )
        ])
        session.commit()

    yield

    FlightORM.metadata.drop_all(bind=test_engine)
    AirportORM.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.app.dependency_overrides, app.authenticate, lambda: "vuta")
    with TestClient(app.app) as test_client:
        yield test_client
