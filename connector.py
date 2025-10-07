#!/usr/bin/env python3

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
import logging

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from lib.sqlmodels import SQLBase, Queue, Track, UnknownFile


class TGMountWebhook(BaseModel):
    fname: str


class DedupWebhook(BaseModel):
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

    logger.info(f"Cleaning destination directory")
    for root, dirs, files in os.walk(args.destdir, topdown=True):
        for file in files:
            os.remove(os.path.join(root, file))
        for dir_ in dirs:
            os.rmdir(os.path.join(root, dir_))
    logger.info(f"Destination directory cleaned")

    logger.info(f"Creating symlinks from database")
    with get_session() as session:
        for track in session.query(Track).filter_by(duplicate=False).all():
            os.symlink(
                src=os.path.join(args.srcdir, track.path),
                dst=os.path.join(args.destdir, track.path),
            )

        for unknown in session.query(UnknownFile).all():
            os.symlink(
                src=os.path.join(args.srcdir, unknown.path),
                dst=os.path.join(args.destdir, unknown.path),
            )

    logger.info(f"Symlinks created")

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


@app.post(
    path="/dedup_webhook"
)
async def dedup_webhook(data: DedupWebhook):
    os.symlink(
        src=os.path.join(args.srcdir, data.fname),
        dst=os.path.join(args.destdir, data.fname),
    )


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Flaczkownia dedup connector")
    parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    parser.add_argument("--basedir", default="./",
                        help="Path prepended to jobs added to queue from webhook")
    parser.add_argument("--srcdir", default="./src/",
                        help="Source directory for symlinks created for deduplicated files")
    parser.add_argument("--destdir", default="./dest/",
                        help="""Destination directory for symlinks created for deduplicated files
                                WARNING: DIRECTORY WILL BE WIPED ON STARTUP!""")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=8000, type=int, help="Port to listen on")
    args = parser.parse_args()

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
