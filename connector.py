#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import uvicorn

from lib.sqlmodels import SQLBase, Queue, Track, UnknownFile, CopyQueue, JobStatus


class TGMountWebhook(BaseModel):
    fname: str
    # Other fields are not important for us here


class DedupFileStatus(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"


class OutputMode(str, Enum):
    SYMLINK = "symlink"
    COPY = "copy"


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


def _process_cleanup_batch(session, batch_files):
    logger.info(f"Starting stale symlinks cleanup - batch of {len(batch_files)} links...")
    # batch_files is a list of (full_path, db_path)
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


def _cleanup_stale_symlinks(view_dir: str, db_prefix: str):
    logger.info("Starting stale symlinks cleanup...")
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


def _ensure_valid_symlinks(view_dir: str, db_prefix: str, source_relative_path: str):
    logger.info("Starting symlink creation and validation...")
    try:
        with sessionmaker(bind=engine)() as session:
            # Process Tracks
            for (path,) in session.query(Track.path).filter_by(duplicate=False).yield_per(1000):
                _create_symlink(path, db_prefix, view_dir, source_relative_path)

            # Process UnknownFiles
            for (path,) in session.query(UnknownFile.path).yield_per(1000):
                _create_symlink(path, db_prefix, view_dir, source_relative_path)

    except Exception:
        logger.exception("Error during symlink creation and validation")


def _resolve_destination_path(source_path: str, source_prefix: str, destination_dir: str) -> Path | None:
    source = Path(source_path)
    prefix = Path(source_prefix)

    try:
        relative_path = source.relative_to(prefix)
    except ValueError:
        logger.warning(f"Source path {source_path} does not start with source prefix {source_prefix}, skipping")
        return None

    return Path(destination_dir) / relative_path


def _enqueue_copy_job(session: Session, source_path: str, destination_path: Path):
    existing = session.query(CopyQueue).filter_by(source_path=source_path).first()

    if existing is not None:
        if existing.status in (JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.DONE):
            logger.debug(f"Copy job for {source_path} already exists with status {existing.status}, skipping enqueue")
            return existing

        if existing.status == JobStatus.FAILED and existing.attempts < args.max_attempts:
            logger.info(f"Requeueing failed copy job for {source_path}")
            existing.destination_path = str(destination_path)
            existing.status = JobStatus.PENDING
            existing.last_error = None
            session.commit()
            return existing

        logger.warning(f"Copy job for {source_path} already failed max attempts, not requeueing")
        return existing

    job = CopyQueue(
        source_path=source_path,
        destination_path=str(destination_path),
        status=JobStatus.PENDING,
    )
    session.add(job)
    session.commit()
    logger.info(f"Enqueued copy job: {source_path} -> {destination_path}")
    return job


def _enqueue_copy_if_missing(session: Session, source_path: str):
    destination_path = _resolve_destination_path(source_path, args.basedir, args.view_dir)
    if destination_path is None:
        return

    if destination_path.exists():
        logger.debug(f"Destination already exists, not enqueueing: {destination_path}")
        return

    _enqueue_copy_job(session, source_path, destination_path)


def _backfill_missing_copies():
    logger.info("Starting copy startup validation/backfill")

    with sessionmaker(bind=engine)() as session:
        for (path,) in session.query(Track.path).filter_by(duplicate=False).yield_per(1000):
            _enqueue_copy_if_missing(session, path)

        for (path,) in session.query(UnknownFile.path).yield_per(1000):
            _enqueue_copy_if_missing(session, path)

    logger.info("Finished copy startup validation/backfill")


def _recover_processing_copy_jobs():
    with sessionmaker(bind=engine)() as session:
        recovered_count = (
            session.query(CopyQueue)
            .filter(CopyQueue.status == JobStatus.PROCESSING)
            .update({"status": JobStatus.PENDING})
        )
        session.commit()

    if recovered_count:
        logger.warning(f"Recovered {recovered_count} interrupted copy jobs")


def _copy_job(job: CopyQueue):
    source_path = Path(job.source_path)
    destination_path = Path(job.destination_path)

    if destination_path.exists():
        logger.info(f"Destination already exists, marking copy job as done: {destination_path}")
        return

    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_destination_path = destination_path.with_name(f".{destination_path.name}.tmp")

    try:
        shutil.copy2(source_path, temporary_destination_path)
        temporary_destination_path.replace(destination_path)
    finally:
        temporary_destination_path.unlink(missing_ok=True)

    logger.info(f"Copied: {source_path} -> {destination_path}")


def _process_one_copy_job() -> bool:
    with sessionmaker(bind=engine)() as session:
        job: CopyQueue | None = (
            session.query(CopyQueue)
            .filter(
                CopyQueue.status.in_((JobStatus.PENDING, JobStatus.FAILED)),
                CopyQueue.attempts < args.max_attempts,
            )
            .order_by(CopyQueue.created_at)
            .first()
        )

        if job is None:
            return False

        updated_count = (
            session.query(CopyQueue)
            .filter(
                CopyQueue.id == job.id,
                CopyQueue.status.in_((JobStatus.PENDING, JobStatus.FAILED)),
                CopyQueue.attempts < args.max_attempts,
            )
            .update({"status": JobStatus.PROCESSING})
        )
        session.commit()

        if updated_count == 0:
            return True

        session.refresh(job)
        logger.info(f"Processing copy job {job.id}: {job.source_path} -> {job.destination_path}")

        try:
            _copy_job(job)
        except Exception as e:
            job.attempts += 1
            job.last_error = str(e)
            job.status = JobStatus.FAILED
            session.commit()
            logger.exception(f"Copy job {job.id} failed, attempt {job.attempts}/{args.max_attempts}")
            return True

        job.status = JobStatus.DONE
        job.last_error = None
        session.commit()
        return True


async def _copy_worker():
    logger.info("Starting copy worker")

    while True:
        try:
            processed = await asyncio.to_thread(_process_one_copy_job)
            if not processed:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Copy worker stopped")
            raise
        except Exception:
            logger.exception("Unexpected error in copy worker")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Initializing database")
    SQLBase.metadata.create_all(engine)
    logger.info("Database initialized")

    worker_task = None

    if args.output_mode == OutputMode.SYMLINK:
        _cleanup_stale_symlinks(args.view_dir, args.db_prefix)
        _ensure_valid_symlinks(args.view_dir, args.db_prefix, args.source_relative_path)

    if args.output_mode == OutputMode.COPY:
        Path(args.view_dir).mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_recover_processing_copy_jobs)
        if args.backfill_on_startup:
            await asyncio.to_thread(_backfill_missing_copies)

        worker_task = asyncio.create_task(_copy_worker())

    yield

    # Shutdown logic
    if worker_task is not None:
        worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    engine.dispose()


app = FastAPI(
    root_path="/api/v1",
    debug=False,
    lifespan=lifespan,
)


@app.post(path="/dedup_processed_file_webhook")
async def dedup_processed_file_webhook(
        data: DedupProcessedFileWebhook,
        session: Annotated[Session, Depends(get_session)],
):
    logger.debug(f"Got dedup processed file webhook: {data}")

    if data.type not in (DedupFileStatus.NEW, DedupFileStatus.UNKNOWN):
        return {"status": "ok"}

    if args.output_mode == OutputMode.SYMLINK:
        _create_symlink(data.path, args.db_prefix, args.view_dir, args.source_relative_path)

    if args.output_mode == OutputMode.COPY:
        destination_path = _resolve_destination_path(data.path, args.basedir, args.view_dir)
        if destination_path is not None and not destination_path.exists():
            _enqueue_copy_job(session, data.path, destination_path)

    return {"status": "ok"}


@app.post(path="/tgmount_add_to_dedup_queue")
async def tgmount_add_to_dedup_queue(data: TGMountWebhook, session: Annotated[Session, Depends(get_session)]):
    q = Queue(path=str(Path(args.basedir) / Path(data.fname)))
    session.add(q)
    session.commit()
    logger.info(f"Added file to queue: {q.path}")

    return {"queue_id": q.id}


def _validate_args(parser: argparse.ArgumentParser, parsed_args: argparse.Namespace):
    symlink_args = (parsed_args.view_dir, parsed_args.source_relative_path, parsed_args.db_prefix)
    copy_args = (parsed_args.view_dir, parsed_args.basedir)

    if parsed_args.output_mode is None:
        if any(symlink_args) or parsed_args.backfill_on_startup:
            parser.error(
                "--view-dir, --source-relative-path, --db-prefix "
                "and --backfill-on-startup require --output-mode."
            )
        return

    if parsed_args.output_mode == OutputMode.SYMLINK:
        if not all(symlink_args):
            parser.error("--output-mode symlink requires --view-dir, --source-relative-path and --db-prefix.")

    if parsed_args.output_mode == OutputMode.COPY:
        if not all(copy_args):
            parser.error("--output-mode copy requires --view-dir and --basedir")


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level="INFO")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Flaczkownia dedup connector")
    parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    parser.add_argument("--basedir", default="./",
                        help="Path prepended to jobs added to queue from webhook")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=8000, type=int, help="Port to listen on")

    parser.add_argument(
        "--output-mode",
        choices=[mode.value for mode in OutputMode],
        type=OutputMode,
        default=OutputMode.SYMLINK,
        help="How accepted dedup files should be exposed. If omitted, connector only handles queue ingestion.",
    )

    parser.add_argument("--view-dir", help="Directory to expose accepted files in")
    parser.add_argument("--source-relative-path", help="Relative path from view-dir to source root")
    parser.add_argument("--db-prefix", help="Prefix to strip from DB paths for symlink mode")

    parser.add_argument(
        "--backfill-on-startup",
        action="store_true",
        help="In copy mode, enqueue all missing non-duplicate tracks and unknown files on startup",
    )
    parser.add_argument("--max-attempts", default=10, type=int, help="Maximum copy attempts per file")

    args = parser.parse_args()
    _validate_args(parser, args)

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)