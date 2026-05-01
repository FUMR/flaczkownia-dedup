#!/usr/bin/env python3

import argparse
import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from lib.sqlmodels import SQLBase, JobStatus, CopyQueue, Track, UnknownFile

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level="INFO")
logger = logging.getLogger(__name__)


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


def _enqueue_if_missing(session: Session, source_path: str):
    destination_path = _resolve_destination_path(source_path, args.source_prefix, args.destination_dir)
    if destination_path is None:
        return

    if destination_path.exists():
        logger.debug(f"Destination already exists, not enqueueing: {destination_path}")
        return

    _enqueue_copy_job(session, source_path, destination_path)


def _backfill_missing_files():
    logger.info("Starting copier startup validation/backfill")

    with sessionmaker(bind=engine)() as session:
        for (path,) in session.query(Track.path).filter_by(duplicate=False).yield_per(1000):
            _enqueue_if_missing(session, path)

        for (path,) in session.query(UnknownFile.path).yield_per(1000):
            _enqueue_if_missing(session, path)

    logger.info("Finished copier startup validation/backfill")


def _recover_processing_jobs():
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


def _process_one_job() -> bool:
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
            processed = await asyncio.to_thread(_process_one_job)
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
    logger.info("Initializing database")
    SQLBase.metadata.create_all(engine)
    logger.info("Database initialized")

    Path(args.destination_dir).mkdir(parents=True, exist_ok=True)


    await asyncio.to_thread(_recover_processing_jobs)
    if args.backfill_on_startup:
        await asyncio.to_thread(_backfill_missing_files)

    worker_task = asyncio.create_task(_copy_worker())

    yield

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
        return {"status": "ignored"}

    destination_path = _resolve_destination_path(data.path, args.source_prefix, args.destination_dir)
    if destination_path is None:
        return {"status": "skipped"}

    if destination_path.exists():
        logger.info(f"Destination already exists, not enqueueing: {destination_path}")
        return {"status": "exists"}

    job = _enqueue_copy_job(session, data.path, destination_path)

    return {"status": job.status.value.lower(), "queue_id": job.id}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flaczkownia dedup copier")
    parser.add_argument(
        "--db",
        "--database",
        default="sqlite:///data/dedup.sqlite3",
        help="Database URL, e.g. sqlite or PostgreSQL URL",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on")
    parser.add_argument("--port", default=9998, type=int, help="Port to listen on")
    parser.add_argument("--source-prefix", required=True, help="Source path prefix to strip from dedup paths")
    parser.add_argument("--destination-dir", required=True, help="Directory to copy accepted files into")
    parser.add_argument(
        "--backfill-on-startup",
        action="store_true",
        help="On startup, enqueue all missing non-duplicate tracks and unknown files",
    )
    parser.add_argument("--max-attempts", default=10, type=int, help="Maximum copy attempts per file")
    args = parser.parse_args()

    engine = create_engine(args.db, echo=False)

    uvicorn.run(app, host=args.host, port=args.port)
