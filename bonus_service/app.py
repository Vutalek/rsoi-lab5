from uuid import UUID, uuid4
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Depends, Query, HTTPException, Response, status

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from utils import construct_engine
from orm import PrivilegeORM, PrivilegeHistoryORM
from models import PrivilegePost, PrivilegePatch, HistoryPost

from auth import authenticate

app = FastAPI(dependencies=[Depends(authenticate)])

engine = construct_engine()

@app.get("/manage/health")
def health():
    return {"status": "healthy"}

###############################
########## Privilege ##########
###############################

@app.get("/api/v1/privileges")
def all_privileges(page: int=1, size: Annotated[int, Query(ge=1, le=100)]=10):
    query = select(PrivilegeORM).order_by(PrivilegeORM.id).limit(size).offset((page-1) * size)
    with Session(engine) as session:
        privileges = session.scalars(query).all()
    privileges = [
        {
            "id": privilege.id,
            "username": privilege.username,
            "balance": privilege.balance,
            "status": privilege.status
        }
        for privilege in privileges
    ]
    return {
        "page": page,
        "pageSize": size,
        "totalElements": len(privileges),
        "items": privileges
    }

@app.get("/api/v1/privileges/{p_id}")
def get_privilege(p_id: int):
    with Session(engine) as session:
        privilege = session.get(PrivilegeORM, p_id)
        if not privilege:
            raise HTTPException(404, detail="Privilege not found")
    privilege = {
        "username": privilege.username,
        "balance": privilege.balance,
        "status": privilege.status
    }
    return privilege

@app.get("/api/v1/privileges/user/{username}")
def get_privilege_by_user(username: str):
    query = select(PrivilegeORM).where(PrivilegeORM.username == username)
    with Session(engine) as session:
        privilege = session.scalar(query)
        if not privilege:
            raise HTTPException(404, detail="Privilege not found")
    privilege = {
        "id": privilege.id,
        "balance": privilege.balance,
        "status": privilege.status
    }
    return privilege

@app.post("/api/v1/privileges")
def make_privilege(body: PrivilegePost):
    get_next_id = select(
        (func.coalesce(func.max(PrivilegeORM.id), 0) + 1)
    )
    with Session(engine) as session:
        next_id = session.scalar(get_next_id)

        new_privilege = PrivilegeORM(
            id=next_id,
            username=body.username,
            status = "BRONZE" if body.status is None else body.status,
            balance=0
        )
        session.add(new_privilege)
        session.commit()
        return Response(
            status_code=status.HTTP_201_CREATED,
            headers={
                "Location": f"/api/v1/privileges/{next_id}"
            }
    )

@app.patch("/api/v1/privileges/{p_id}")
def update_privilege(p_id: str, body: PrivilegePatch):
    with Session(engine) as session:
        privilege = session.get(PrivilegeORM, p_id)
        if not privilege:
            raise HTTPException(404, detail="Privilege not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(privilege, field, value)

        session.commit()
        session.refresh(privilege)
    return privilege

@app.delete("/api/v1/privileges/{p_id}")
def delete_privilege(p_id: str):
    with Session(engine) as session:
        privilege = session.get(PrivilegeORM, p_id)

        if privilege is not None:
            session.delete(privilege)
            session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

#######################################
########## Privilege History ##########
#######################################

@app.get("/api/v1/history/{p_id}")
def get_history(p_id: int):
    query = select(PrivilegeHistoryORM).where(PrivilegeHistoryORM.privilege_id == p_id)
    with Session(engine) as session:
        history = session.scalars(query).all()
    history = [
        {
            "id": h.id,
            "ticket_uid": h.ticket_uid,
            "datetime": h.datetime,
            "balance_diff": h.balance_diff,
            "operation_type": h.operation_type
        }
        for h in history
    ]
    return history

@app.get("/api/v1/history/entry/{e_id}")
def get_history_entry(e_id: int):
    with Session(engine) as session:
        entry = session.get(PrivilegeHistoryORM, e_id)
    entry = {
        "privilege_id": entry.privilege_id,
        "ticket_uid": entry.ticket_uid,
        "datetime": entry.datetime,
        "balance_diff": entry.balance_diff,
        "operation_type": entry.operation_type
    }
    return entry

@app.post("/api/v1/history/cancel/{ticket_uid}")
def cancel_history(ticket_uid: UUID):
    with Session(engine) as session:
        entries = session.scalars(select(PrivilegeHistoryORM).where(
            PrivilegeHistoryORM.ticket_uid == ticket_uid
        )).all()
        if not entries:
            raise HTTPException(404, detail="Ticket history not found")
        balance_diff = sum(
            entry.balance_diff if entry.operation_type == "FILL_IN_BALANCE"
            else -entry.balance_diff for entry in entries
        )
        if balance_diff:
            privilege = session.get(PrivilegeORM, entries[0].privilege_id)
            privilege.balance -= balance_diff
            session.add(PrivilegeHistoryORM(
                id=session.scalar(select(func.coalesce(func.max(PrivilegeHistoryORM.id), 0) + 1)),
                privilege_id=privilege.id,
                ticket_uid=ticket_uid,
                datetime=datetime.now(),
                balance_diff=abs(balance_diff),
                operation_type="DEBIT_THE_ACCOUNT" if balance_diff > 0 else "FILL_IN_BALANCE"
            ))
            session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/history/{p_id}")
def make_history(p_id: int, body: HistoryPost):
    get_next_id = select(
        (func.coalesce(func.max(PrivilegeHistoryORM.id), 0) + 1)
    )
    with Session(engine) as session:
        next_id = session.scalar(get_next_id)

        new_entry = PrivilegeHistoryORM(
            id=next_id,
            privilege_id=p_id,
            ticket_uid=body.ticket_uid,
            datetime=body.datetime,
            balance_diff=body.balance_diff,
            operation_type=body.operation_type
        )

        privilege = session.get(PrivilegeORM, p_id)
        if privilege is None:
            raise HTTPException(404, detail="Privilege not found")

        session.add(new_entry)

        if new_entry.operation_type == "FILL_IN_BALANCE":
            privilege.balance += new_entry.balance_diff
        else:
            privilege.balance -= new_entry.balance_diff
            
        session.commit()
        return Response(
            status_code=status.HTTP_201_CREATED,
            headers={
                "Location": f"/api/v1/history/entry/{next_id}"
            }
    )
