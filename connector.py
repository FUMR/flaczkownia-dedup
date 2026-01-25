#!/usr/bin/env python3

import argparse
import logging
import os
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from lib.sqlmodels import SQLBase, Queue, Track, UnknownFile


class TGMountWebhook(BaseModel):
    fname: str


class DedupFileStatus(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"


class DedupProcessedFileWebhook(BaseModel):
    path: str
    type: DedupFileStatus
    audioprint: str | None = None
    metadata: dict | None = None


def get_session():
    with sessionmaker(bind=engine)() as session:
        yield session


def _create_symlink(db_path: str):
    try:
        if not db_path.startswith(args.db_prefix):
            logger.warning(f"Path {db_path} does not start with {args.db_prefix}, skipping")
            return

        rel_path = Path(db_path).relative_to(args.db_prefix)
        link_path = Path(args.view_dir) / rel_path

        # Calculate target
        # link is at view_dir/rel_path
        # target is at view_dir/source_relative_path/rel_path
        # We need to go up from link_path.parent to view_dir
        depth = len(rel_path.parent.parts)
        up_prefix = "../" * depth
        target = f"{up_prefix}{args.source_relative_path}/{rel_path}"

        if link_path.is_symlink():
            current_target = os.readlink(link_path)
            if current_target == target:
                return
            else:
                logger.info(f"Updating symlink {link_path}: {current_target} -> {target}")
                link_path.unlink()
        elif link_path.exists():
             logger.warning(f"Path {link_path} exists and is not a symlink, skipping")
             return

        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path)
        logger.debug(f"Created symlink: {link_path} -> {target}")

    except Exception as e:
        logger.error(f"Failed to create symlink for {db_path}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info(f"Initializing database")
    SQLBase.metadata.create_all(engine)
    logger.info(f"Database initialized")

    if args.view_dir and args.source_relative_path:
        logger.info("Starting view reconciliation...")
        try:
            with sessionmaker(bind=engine)() as session:
                tracks = session.query(Track.path).filter_by(duplicate=False).all()
                unknown = session.query(UnknownFile.path).all()
                
                valid_paths = set()
                for (path,) in tracks + unknown:
                    _create_symlink(path)
                    if path.startswith(args.db_prefix):
                         valid_paths.add(str(Path(args.view_dir) / Path(path).relative_to(args.db_prefix)))

                # Cleanup stale
                for root, dirs, files in os.walk(args.view_dir, topdown=False):
                     for name in files:
                         full_path = str(Path(root) / name)
                         if full_path not in valid_paths:
                             logger.info(f"Removing stale file/link: {full_path}")
                             os.unlink(full_path)
                     for name in dirs:
                         try:
                            os.rmdir(os.path.join(root, name))
                         except OSError:
                            pass # Not empty

        except Exception as e:
            logger.exception("Error during view reconciliation")

    yield

    # Shutdown logic
    engine.dispose()


app = FastAPI(
    root_path="/api/v1",
    debug=False,
    lifespan=lifespan,
)


@app.post(
    path="/dedup_processed_file_webhook"
)
async def dedup_processed_file_webhook(data: DedupProcessedFileWebhook):
    if args.view_dir and args.source_relative_path:
        if data.type in (DedupFileStatus.NEW, DedupFileStatus.UNKNOWN):
            _create_symlink(data.path)
    
    return {"status": "ok"}


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
    parser.add_argument("--view-dir", help="Directory to create symlink view in")
    parser.add_argument("--source-relative-path", help="Relative path from view-dir to source root")
    parser.add_argument("--db-prefix", default="data/music/", help="Prefix to strip from DB paths")
    
    args = parser.parse_args()

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
