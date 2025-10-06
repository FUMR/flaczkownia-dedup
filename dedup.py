#!/usr/bin/env python3

import argparse
import logging
import os
from time import sleep

import audioprint
import librosa
import mediafile
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


def process_path(path, session):
    logger.info(f"Processing path: {path}")

    for file in _recursive_path_walk(path):
        logger.info(f"Processing file: {file}")

        # Skip already indexed
        if session.query(Track).filter_by(path=file).first() or session.query(UnknownFile).filter_by(path=file).first():
            logger.info(f"Skipping already indexed file: {file}")
            continue

        try:
            mf = MediaFile(file)
        except mediafile.FileTypeError:
            uf = UnknownFile(path=file)
            session.add(uf)
            session.commit()
            logger.info(f"Skipping file in unsupported format: {file}")
            continue

        fp = _audioprint_resampled(file)

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


def main():
    parser = argparse.ArgumentParser(description="Flaczkownia dedup daemon")
    parser.add_argument("--directory", help="Path to flaczkownia directory. Starts in queue mode if not provided.")
    parser.add_argument("--db", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    args = parser.parse_args()

    logger.info("Initializing database")
    engine = create_engine(args.db, echo=False)
    SQLBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    logger.info("Database initialized")

    if args.directory:
        process_path(args.directory, session)
        return

    while True:
        try:
            job: Queue | None = session.query(Queue).filter_by(status=JobStatus.PENDING).order_by(
                Queue.created_at).first()

            if job is None:
                sleep(1)
                continue

            logger.info(f"Starting processing of job with queue_id: {job.id}")
            job.update_status(JobStatus.PROCESSING, session)

            try:
                process_path(job.path, session)
            except Exception as e:
                job.update_status(JobStatus.FAILED, session)
                logger.exception("Job failed")
                continue

            job.update_status(JobStatus.DONE, session)
            logger.info("Job done")
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
