#!/bin/env python3

import argparse
from contextlib import asynccontextmanager
from typing import Annotated
import logging

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from lib.sqlmodels import SQLBase, Queue


class TGMountWebhook(BaseModel):
    msg_id: int
    chat_id: int
    sender_id: int
    fname: str

    mimetype: str
    size: int

    voice: bool
    video: bool

    fwd_sender_id: int | None = None
    reply_to_msg_id: int | None = None
    reply_to_sender_id: int | None = None


def get_session():
    with sessionmaker(bind=engine)() as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info(f"Initializing database")
    SQLBase.metadata.create_all(engine)
    logger.info(f"Database initialized")

    yield

    # Shutdown logic
    engine.dispose()


app = FastAPI(
    root_path="/api/v1",
    debug=False,
    lifespan=lifespan,
)


@app.post(
    path="/tgmount_webhook"
)
async def dedup(data: TGMountWebhook, session: Annotated[sessionmaker, Depends(get_session)]):
    q = Queue(path=data.fname)
    session.add(q)
    session.commit()

    return {"queue_id": q.id}


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Flaczkownia dedup tgmount webhook server")
    parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=8000, help="Port to listen on")
    args = parser.parse_args()

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
