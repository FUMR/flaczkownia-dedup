#!/usr/bin/env python3

import argparse
import logging
import multiprocessing
import os
from time import sleep

import audioprint
import httpx
import librosa
import mediafile
import puremagic
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from mediafile import MediaFile

from lib.sqlmodels import SQLBase, Track, Queue, JobStatus, UnknownFile

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
logger = logging.getLogger(__name__)


def _recursive_path_walk(path):
    if not os.path.exists(path):
        return
    elif os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for file in files:
                yield os.path.join(root, file)
    else:
        yield path


def _audioprint_resampled(file_path):
    raw_pcm_data, sr = audioprint.read_audio_file(file_path)
    if sr != 44100:
        # workaround for different hashes for different sample rates
        raw_pcm_data = librosa.resample(raw_pcm_data, orig_sr=sr, target_sr=44100)

    return audioprint.audio_phash(raw_pcm_data, 44100)


def _send_webhook(urls, payload):
    if not urls:
        return
    for url in urls:
        try:
            httpx.post(url, json=payload, timeout=2.0)
        except Exception as e:
            logger.warning(f"Failed to send webhook to {url}: {e}")


def process_path(path, session, multiprocess_pool, webhook_urls=None):
    logger.info(f"Processing path: {path}")

    for file in _recursive_path_walk(path):
        logger.info(f"Processing file: {file}")

        # Skip already indexed
        if session.query(Track).filter_by(path=file).first() or session.query(UnknownFile).filter_by(path=file).first():
            logger.info(f"Skipping already indexed file: {file}")
            continue

        try:
            mimes = puremagic.magic_file(file)
            if not any(m.mime_type.startswith("audio/") for m in mimes):
                raise ValueError("Not an audio file")
        except (ValueError, puremagic.PureError):
            uf = UnknownFile(path=file)
            session.add(uf)
            session.commit()
            logger.info(f"Skipping file in unsupported format: {file}")
            _send_webhook(webhook_urls, {"path": file, "type": "unknown"})
            continue

        try:
            mf = MediaFile(file)
        except mediafile.FileTypeError:
            uf = UnknownFile(path=file)
            session.add(uf)
            session.commit()
            logger.info(f"Skipping file in unsupported format: {file}")
            _send_webhook(webhook_urls, {"path": file, "type": "unknown"})
            continue

        fp = multiprocess_pool.apply(_audioprint_resampled, (file,))

        # Check if the same track already exists
        existing = session.query(Track).filter_by(
            acoustic_fingerprint=fp,
            album=mf.album,
            mb_albumid=mf.mb_albumid,
            disc_number=mf.disc,
            track_number=mf.track,
        ).first()

        track = Track(
            path=file,
            acoustic_fingerprint=fp,
            album=mf.album,
            mb_albumid=mf.mb_albumid,
            disc_number=mf.disc,
            track_number=mf.track,
            duplicate=existing is not None,
        )

        session.add(track)
        session.commit()

        logger.info(f"Processed file: {file}, duplicate={existing is not None}")

        type_str = "duplicate" if existing is not None else "new"
        payload = {
            "path": file,
            "type": type_str,
            "audioprint": str(fp),
            "metadata": None
        }
        try:
             payload["metadata"] = {
                 "album": mf.album,
                 "title": mf.title,
                 "artist": mf.artist,
                 "year": mf.year
             }
        except:
             pass

        _send_webhook(webhook_urls, payload)


def main():
    parser = argparse.ArgumentParser(description="Flaczkownia dedup daemon")
    parser.add_argument("--directory", help="Path to flaczkownia directory. Starts in queue mode if not provided.")
    parser.add_argument("--db", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    parser.add_argument("--webhook-url", action="append", help="Webhook URL to notify about processed files")
    args = parser.parse_args()

    logger.info("Initializing database")
    engine = create_engine(args.db, echo=False)
    SQLBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    logger.info("Database initialized")

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=1, maxtasksperchild=50) as multiprocess_pool:
        if args.directory:
            process_path(args.directory, session, multiprocess_pool, args.webhook_url)
            return

        while True:
            try:
                job: Queue | None = session.query(Queue).filter_by(status=JobStatus.PENDING).order_by(
                    Queue.created_at).first()

                if job is None:
                    sleep(1)
                    continue

                logger.info(f"Picking job with queue_id: {job.id}")

                # Only try to set to PROCESSING if it's still PENDING to avoid race conditions in multiple workers setups
                updated_count = session.query(Queue).filter(
                    Queue.id == job.id,
                    Queue.status == JobStatus.PENDING
                ).update({"status": JobStatus.PROCESSING})
                session.commit()

                if updated_count == 0:
                    logger.info(f"Job {job.id} picked by another worker, skipping")
                    continue

                session.refresh(job)

                logger.info(f"Starting processing of job with queue_id: {job.id}")

                try:
                    process_path(job.path, session, multiprocess_pool, args.webhook_url)
                except Exception as e:
                    job.status = JobStatus.FAILED
                    session.commit()
                    logger.exception(f"Job {job.id} failed")
                    continue

                job.status = JobStatus.DONE
                session.commit()
                logger.info(f"Job {job.id} done")
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    main()
