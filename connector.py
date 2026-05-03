#!/usr/bin/env python3

import argparse
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import uvicorn

from lib.sqlmodels import SQLBase, Queue, Track, UnknownFile

executor: ThreadPoolExecutor | None = None
_file_op = None


class TGMountWebhook(BaseModel):
    fname: str
    # Other fields are not important for us here


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


def _create_symlink(db_path: str, db_prefix: str, view_dir: str, source_relative_path: str):
    try:
        if not db_path.startswith(db_prefix):
            logger.warning(f"Path {db_path} does not start with {db_prefix}, skipping")
            return

        rel_path = Path(db_path).relative_to(db_prefix)
        link_path = Path(view_dir) / rel_path

        # Calculate the target
        # link is at view_dir/rel_path
        # target is at view_dir/source_relative_path/rel_path
        # We need to go up from link_path.parent to view_dir
        depth = len(rel_path.parent.parts)
        up_prefix = "../" * depth
        target = f"{up_prefix}{source_relative_path}/{rel_path}"

        if link_path.is_symlink():
            current_target = os.readlink(link_path)
            if current_target == target:
                return
            else:
                logger.debug(f"Updating symlink {link_path}: {current_target} -> {target}")
                link_path.unlink()
        elif link_path.exists():
             logger.warning(f"Path {link_path} exists and is not a symlink, skipping")
             return

        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path)
        logger.debug(f"Created symlink: {link_path} -> {target}")

    except Exception as e:
        logger.error(f"Failed to create symlink for {db_path}: {e}")


def _copy_file(db_path: str, db_prefix: str, view_dir: str, source_path: str):
    try:
        if not db_path.startswith(db_prefix):
            logger.warning(f"Path {db_path} does not start with {db_prefix}, skipping")
            return

        rel_path = Path(db_path).relative_to(db_prefix)
        src_file = Path(source_path) / rel_path
        dst_file = Path(view_dir) / rel_path

        if dst_file.exists() and not dst_file.is_symlink():
            src_stat = os.stat(src_file)
            dst_stat = os.stat(dst_file)
            if src_stat.st_size == dst_stat.st_size and src_stat.st_mtime == dst_stat.st_mtime:
                logger.debug(f"Copy up to date: {dst_file} (size/mtime equals)")
                return
            logger.debug(f"Updating copy: {dst_file} (size/mtime differs)")
            dst_file.unlink()

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = dst_file.with_suffix(dst_file.suffix + ".tmp")
        shutil.copy2(src_file, tmp_file)
        tmp_file.replace(dst_file)
        logger.debug(f"Copied: {src_file} -> {dst_file}")

    except Exception as e:
        logger.error(f"Failed to copy {db_path}: {e}")


def _process_cleanup_batch(session, batch_files):
    logger.info(f"Starting stale files cleanup - batch of {len(batch_files)} files...")
    db_paths = [b[1] for b in batch_files]

    valid_tracks = session.query(Track.path).filter(Track.path.in_(db_paths), Track.duplicate == False).all()
    valid_unknown = session.query(UnknownFile.path).filter(UnknownFile.path.in_(db_paths)).all()

    valid_db_paths = set(p[0] for p in valid_tracks + valid_unknown)

    for full_path, db_path in batch_files:
        if db_path not in valid_db_paths:
            logger.debug(f"Removing stale file/link: {full_path}")
            try:
                os.unlink(full_path)
            except OSError as e:
                logger.error(f"Failed to remove {full_path}: {e}")


def _cleanup_stale_files(view_dir: str, db_prefix: str):
    logger.info("Starting stale files cleanup...")
    batch_size = 1000
    batch_files = []  # list of (full_path, db_path)

    try:
        # Pass 1: Remove stale files
        with sessionmaker(bind=engine)() as session:
            for root, dirs, files in os.walk(view_dir, topdown=False):
                for name in files:
                    full_path = os.path.join(root, name)
                    try:
                        rel_path = Path(full_path).relative_to(view_dir)
                        # Reconstruct db_path
                        db_path = str(Path(db_prefix) / rel_path)
                        batch_files.append((full_path, db_path))
                    except ValueError:
                        continue

                    if len(batch_files) >= batch_size:
                        _process_cleanup_batch(session, batch_files)
                        batch_files = []

            # Process remaining
            if batch_files:
                _process_cleanup_batch(session, batch_files)
        
        # Pass 2: Clean empty directories
        for root, dirs, files in os.walk(view_dir, topdown=False):
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    pass  # Not empty

    except Exception:
        logger.exception("Error during stale file cleanup")

    logger.info("Starting stale files finished")


def _ensure_valid_view(view_dir: str, db_prefix: str):
    logger.info("Starting view reconciliation...")
    try:
        with sessionmaker(bind=engine)() as session:
            # Process Tracks
            for (path,) in session.query(Track.path).filter_by(duplicate=False).yield_per(1000):
                _file_op(path)

            # Process UnknownFiles
            for (path,) in session.query(UnknownFile.path).yield_per(1000):
                _file_op(path)

    except Exception:
        logger.exception("Error during view reconciliation")

    logger.info("View reconciliation finished")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global executor, _file_op

    # Startup logic
    logger.info("Initializing database")
    SQLBase.metadata.create_all(engine)
    logger.info("Database initialized")

    executor = ThreadPoolExecutor(max_workers=1)

    if args.view_mode == "symlink":
        _file_op = partial(_create_symlink, db_prefix=args.db_prefix, view_dir=args.view_dir, source_relative_path=args.source_relative_path)
    elif args.view_mode == "copy":
        _file_op = partial(_copy_file, db_prefix=args.db_prefix, view_dir=args.view_dir, source_path=args.source_path)

    if _file_op:
        executor.submit(_cleanup_stale_files, args.view_dir, args.db_prefix)
        executor.submit(_ensure_valid_view, args.view_dir, args.db_prefix)

    yield

    # Shutdown logic
    executor.shutdown(wait=False)
    engine.dispose()


app = FastAPI(
    root_path="/api/v1",
    debug=False,
    lifespan=lifespan,
)


@app.post(path="/dedup_processed_file_webhook")
async def dedup_processed_file_webhook(data: DedupProcessedFileWebhook):
    logger.debug(f"Got dedup processed file webhook: {data}")
    if data.type in (DedupFileStatus.NEW, DedupFileStatus.UNKNOWN) and _file_op:
        executor.submit(_file_op, data.path)

    return {"status": "ok"}


@app.post(path="/tgmount_add_to_dedup_queue")
async def tgmount_add_to_dedup_queue(data: TGMountWebhook, session: Annotated[Session, Depends(get_session)]):
    q = Queue(path=str(Path(args.basedir) / Path(data.fname)))
    session.add(q)
    session.commit()
    logger.info(f"Added file to queue: {q.path}")

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

    parser.add_argument("--view-mode", type=str.lower, choices=["symlink", "copy"],
                        help="Mode of deduplicated view")
    parser.add_argument("--view-dir", help="Directory to create view in")
    parser.add_argument("--db-prefix", help="Prefix to strip from DB paths before symlinking")
    parser.add_argument("--source-relative-path",
                        help="Relative path from view-dir to source root (symlink target)")
    parser.add_argument("--source-path", help="Path where original files are stored (copy source)",)

    args = parser.parse_args()

    if args.view_mode == "symlink":
        if None in (args.view_dir, args.db_prefix, args.source_relative_path):
            parser.error("--view-mode symlink: requires --view-dir, --db-prefix and --source-relative-path.")
    elif args.view_mode == "copy":
        if None in (args.view_dir, args.db_prefix, args.source_path):
            parser.error("--view-mode copy: requires --view-dir, --db-prefix and --source-path.")

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
