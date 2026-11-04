import os
from uuid import UUID
from datetime import datetime as dtime
from typing import Annotated

import requests
from fastapi import FastAPI, Depends, Query, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse

from circuit_breaker import CircuitBreaker
from models import TicketBuyPost
from rabbit import post_or_queue

from auth import authenticate

app = FastAPI(dependencies=[Depends(authenticate)])
flight_service = os.environ.get("FLIGHT_SERVICE_HOST", "")
flight_cb = CircuitBreaker()
ticket_service = os.environ.get("TICKET_SERVICE_HOST", "")
ticket_cb = CircuitBreaker()
bonus_service = os.environ.get("BONUS_SERVICE_HOST", "")
bonus_cb = CircuitBreaker()


def service_request(method, url, **kwargs):
    response = requests.request(method, url, **kwargs)
    if response.status_code == 401:
        raise HTTPException(401, "Invalid access token", headers={"WWW-Authenticate": "Bearer"})
    return response


@app.get("/manage/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/flights")
def get_all_flights(authorization: Annotated[str, Header()], page: int=1, size: Annotated[int, Query(ge=1, le=100)]=10):
    @flight_cb.check_circuit
    def request():
        return service_request("GET", flight_service + f"/api/v1/flights?page={page}&size={size}", headers={"Authorization": authorization}).json()
    status, flights = request()
    if not status:
        flights = {
            "page": page,
            "pageSize": size,
            "totalElements": 0,
            "items": []
        }
    return flights

@app.get("/api/v1/tickets")
def get_all_user_tickets(username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()]):
    tickets = service_request("GET", ticket_service + f"/api/v1/tickets/user/{username}", headers={"Authorization": authorization}).json()
    extended_tickets = []
    for ticket in tickets:
        @flight_cb.check_circuit
        def request():
            return service_request("GET", flight_service + f"/api/v1/flights/{ticket.get('flightNumber', '')}", headers={"Authorization": authorization}).json()
        status, flight = request()
        if not status:
            flight = {}
        extended_tickets.append(
            {
                "ticketUid": ticket.get("ticketUid"),
                "flightNumber": flight.get("flightNumber", ""),
                "fromAirport": flight.get("fromAirport", ""),
                "toAirport": flight.get("toAirport", ""),
                "date": flight.get("date", ""),
                "price": flight.get("price", ""),
                "status": ticket.get("status", "")
            }
        )
    return extended_tickets

@app.post("/api/v1/tickets")
def buy_ticket(username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()], body: TicketBuyPost):
    # получаем бонусный счёт до создания билета
    try:
        privilege = service_request("GET", bonus_service + f"/api/v1/privileges/user/{username}", timeout=5, headers={"Authorization": authorization})
        privilege.raise_for_status()
    except requests.RequestException:
        return JSONResponse(status_code=503, content={"message": "Bonus Service unavailable"})

    # создаём билет
    ticket_uid = service_request("POST",
        ticket_service + "/api/v1/tickets",
        json={
            "username": username,
            "flight_number": body.flightNumber,
            "price": body.price
        }, headers={"Authorization": authorization}
    ).headers["Location"].split('/')[-1]

    current_datetime = dtime.now().isoformat(sep=' ')

    # проводим расчёт бонусов
    if body.paidFromBalance and privilege.status_code == 200:
        difference = body.price - privilege.json().get("balance", 0)
        if difference <= 0:
            balance_diff = body.price
            paid_by_money = 0
            paid_by_bonuses = body.price
        else:
            balance_diff = privilege.json().get("balance", 0)
            paid_by_money = difference
            paid_by_bonuses = privilege.json().get("balance", 0)
        history_done = post_or_queue(
            bonus_service + f"/api/v1/history/{privilege.json().get('id')}",
            json={
                "ticket_uid": ticket_uid,
                "datetime": current_datetime,
                "balance_diff": balance_diff,
                "operation_type": "DEBIT_THE_ACCOUNT"
            }, headers={"Authorization": authorization}
        )
    else:
        history_done = post_or_queue(
            bonus_service + f"/api/v1/history/{privilege.json().get('id')}",
            json={
                "ticket_uid": ticket_uid,
                "datetime": current_datetime,
                "balance_diff": int(body.price * 0.1),
                "operation_type": "FILL_IN_BALANCE"
            }, headers={"Authorization": authorization}
        )
        paid_by_money = body.price
        paid_by_bonuses = 0

    # меняем статус билета
    post_or_queue(ticket_service + f"/api/v1/tickets/pay/{ticket_uid}", headers={"Authorization": authorization})

    # собираем всю информацию по билету
    flight = service_request("GET", flight_service + f"/api/v1/flights/{body.flightNumber}", headers={"Authorization": authorization}).json()
    current_privilege = service_request("GET", bonus_service + f"/api/v1/privileges/user/{username}", headers={"Authorization": authorization}).json() if history_done else privilege.json()
    response = {
        "ticketUid": ticket_uid,
        "flightNumber": flight.get("flightNumber", ""),
        "fromAirport": flight.get("fromAirport", ""),
        "toAirport": flight.get("toAirport", ""),
        "date": flight.get("date", ""),
        "price": flight.get("price", ""),
        "paidByMoney": paid_by_money,
        "paidByBonuses": paid_by_bonuses,
        "status": "PAID",
        "privilege": {
            "balance": current_privilege.get("balance", 0),
            "status": current_privilege.get("status", "BRONZE")
        }
    }
    return response

@app.get("/api/v1/tickets/{ticket_uid}")
def get_ticket(ticket_uid: UUID, username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()]):
    ticket = service_request("GET", ticket_service + f"/api/v1/tickets/{ticket_uid}", headers={"Authorization": authorization})
    if ticket.status_code == 404:
        raise HTTPException("Ticket not found!")
    ticket = ticket.json()

    @flight_cb.check_circuit
    def request():
        return service_request("GET", flight_service + f"/api/v1/flights/{ticket.get('flightNumber', '')}", headers={"Authorization": authorization}).json()
    status, flight = request()
    if not status:
        flight = {}

    response = {
        "ticketUid": ticket_uid,
        "flightNumber": flight.get("flightNumber", ""),
        "fromAirport": flight.get("fromAirport", ""),
        "toAirport": flight.get("toAirport", ""),
        "date": flight.get("date", ""),
        "price": flight.get("price", ""),
        "status": ticket.get("status", "")
    }
    return response

@app.delete("/api/v1/tickets/{ticket_uid}")
def get_ticket(ticket_uid: UUID, username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()]):
    response = service_request("POST", ticket_service + f"/api/v1/tickets/cancel/{ticket_uid}", headers={"Authorization": authorization})
    if response.status_code == 200:
        post_or_queue(bonus_service + f"/api/v1/history/cancel/{ticket_uid}", headers={"Authorization": authorization})
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    else:
        raise HTTPException(404, "Ticket not found")

@app.get("/api/v1/me")
def get_me(username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()]):
    tickets = service_request("GET", ticket_service + f"/api/v1/tickets/user/{username}", headers={"Authorization": authorization}).json()
    extended_tickets = []
    for ticket in tickets:
        @flight_cb.check_circuit
        def request1():
            return service_request("GET", flight_service + f"/api/v1/flights/{ticket.get('flightNumber', '')}", headers={"Authorization": authorization}).json()
        status, flight = request1()
        if not status:
            flight = {}
        extended_tickets.append(
            {
                "ticketUid": ticket.get("ticketUid"),
                "flightNumber": flight.get("flightNumber", ""),
                "fromAirport": flight.get("fromAirport", ""),
                "toAirport": flight.get("toAirport", ""),
                "date": flight.get("date", ""),
                "price": flight.get("price", ""),
                "status": ticket.get("status", "")
            }
        )

    @bonus_cb.check_circuit
    def request2():
        response = service_request("GET", bonus_service + f"/api/v1/privileges/user/{username}", timeout=5, headers={"Authorization": authorization})
        response.raise_for_status()
        return response.json()
    status, privilege = request2()
    if not status:
        privilege = {}

    response = {
        "tickets": extended_tickets,
        "privilege": {
            "balance": privilege.get("balance"),
            "status": privilege.get("status")
        } if status else {}
    }
    return response

@app.get("/api/v1/privilege")
def get_privilege(username: Annotated[str, Depends(authenticate)], authorization: Annotated[str, Header()]):
    try:
        privilege = service_request("GET", bonus_service + f"/api/v1/privileges/user/{username}", timeout=5, headers={"Authorization": authorization})
        privilege.raise_for_status()
        privilege = privilege.json()
        history = service_request("GET", bonus_service + f"/api/v1/history/{privilege.get('id', '')}", timeout=5, headers={"Authorization": authorization})
        history.raise_for_status()
        history = history.json()
    except requests.RequestException:
        return JSONResponse(status_code=503, content={"message": "Bonus Service unavailable"})

    response = {
        "balance": privilege.get("balance"),
        "status": privilege.get("status"),
        "history": [
            {
                "date": h.get("datetime", ""),
                "ticketUid": h.get("ticket_uid", ""),
                "balanceDiff": h.get("balance_diff", 0),
                "operationType": h.get("operation_type", "")
            }
            for h in history
        ]
    }
    return response
