from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.db.models import Item
from src.db.session import get_session

app = FastAPI(title="python-postgresql-template")

SessionDep = Annotated[Session, Depends(get_session)]


class ItemIn(BaseModel):
    name: str


class ItemOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


@app.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/items", response_model=list[ItemOut])
def list_items(session: SessionDep) -> list[Item]:
    return list(session.scalars(select(Item).order_by(Item.id)))


@app.post("/items", response_model=ItemOut)
def create_item(payload: ItemIn, session: SessionDep) -> Item:
    item = Item(name=payload.name)
    session.add(item)
    session.commit()
    return item
