from uuid import UUID, uuid4

from fastapi import FastAPI, Depends, HTTPException, Response, status

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from utils import construct_engine
from orm import TicketORM
from models import TicketPost

from auth import authenticate

app = FastAPI(dependencies=[Depends(authenticate)])

engine = construct_engine()

@app.get("/manage/health")
def health():
    return {"status": "healthy"}

@app.get("/api/v1/tickets/user/{username}")
def all_user_tickets(username: str):
    query = select(TicketORM).where(TicketORM.username == username)
    with Session(engine) as session:
        tickets = session.scalars(query).all()
    tickets = [
        {
            "ticketUid": ticket.ticket_uid,
            "flightNumber": ticket.flight_number,
            "price": ticket.price,
            "status": ticket.status
        }
        for ticket in tickets
    ]
    return tickets

@app.get("/api/v1/tickets/{ticket_uid}")
def all_user_tickets(ticket_uid: UUID):
    query = select(TicketORM).where(TicketORM.ticket_uid == ticket_uid)
    with Session(engine) as session:
        ticket = session.scalar(query)
        if not ticket:
            raise HTTPException(404, detail="Ticket not found")
    ticket = {
        "username": ticket.username,
        "flightNumber": ticket.flight_number,
        "price": ticket.price,
        "status": ticket.status
    }
    return ticket

@app.post("/api/v1/tickets/")
def buy_ticket(body: TicketPost):
    get_next_id = select(
        (func.coalesce(func.max(TicketORM.id), 0) + 1)
    )
    with Session(engine) as session:
        next_id = session.scalar(get_next_id)
        new_uuid = uuid4()

        new_ticket = TicketORM(
            id=next_id,
            ticket_uid=new_uuid,
            username=body.username,
            flight_number=body.flight_number,
            price=body.price,
            status="INVOICE"
        )
        session.add(new_ticket)
        session.commit()
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers={
            "Location": f"/api/v1/tickets/{new_uuid}"
        }
    )

@app.post("/api/v1/tickets/pay/{ticket_uid}")
def pay_ticket(ticket_uid: UUID):
    get_ticket = select(TicketORM).where(TicketORM.ticket_uid == ticket_uid)
    with Session(engine) as session:
        ticket = session.scalar(get_ticket)
        if not ticket:
            raise HTTPException(404, detail="Ticket not found")
        ticket.status = "PAID"

        session.commit()
        session.refresh(ticket)
    return ticket

@app.post("/api/v1/tickets/cancel/{ticket_uid}")
def cancel_ticket(ticket_uid: UUID):
    get_ticket = select(TicketORM).where(TicketORM.ticket_uid == ticket_uid)
    with Session(engine) as session:
        ticket = session.scalar(get_ticket)
        if not ticket:
            raise HTTPException(404, detail="Ticket not found")
        ticket.status = "CANCELED"

        session.commit()
        session.refresh(ticket)
    return ticket
 