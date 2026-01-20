#!/usr/bin/env python3

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
import logging

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from lib.sqlmodels import SQLBase, Queue


class TGMountWebhook(BaseModel):
    fname: str


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
    path="/tgmount_add_to_dedup_queue"
)
async def tgmount_add_to_dedup_queue(data: TGMountWebhook, session: Annotated[sessionmaker, Depends(get_session)]):
    q = Queue(path=str(Path(args.basedir) / Path(data.fname)))
    session.add(q)
    session.commit()

    return {"queue_id": q.id}


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Flaczkownia dedup connector")
    parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    parser.add_argument("--basedir", default="./",
                        help="Path prepended to jobs added to queue from webhook")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=8000, type=int, help="Port to listen on")
    args = parser.parse_args()

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
