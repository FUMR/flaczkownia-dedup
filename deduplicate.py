import argparse
import logging
import os
from typing import Tuple

import sqlalchemy as sa
from mediafile import MediaFile
from sqlalchemy.orm import sessionmaker

from audioprint import fingerprint_file

Base = sa.orm.declarative_base()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
logger = logging.getLogger(__name__)

class Track(Base):
    __tablename__ = "tracks"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    message_id = sa.Column(sa.Integer, nullable=False)
    path = sa.Column(sa.String, unique=True, nullable=False)
    track_number = sa.Column(sa.Integer, nullable=False)
    disc_number = sa.Column(sa.Integer, nullable=False)
    album = sa.Column(sa.String, nullable=False)
    audioprint = sa.Column(sa.Integer, nullable=False)
    duplicate = sa.Column(sa.Boolean, default=False)


def get_metadata(path) -> Tuple[str, int, int]:
    mf = MediaFile(path)
    album = mf.album or ""
    track_number = mf.track or 0
    disc_number = mf.disc or 1
    return album, track_number, disc_number


def get_audioprint(path) -> int | None:
    try:
        return fingerprint_file(path)
    except Exception as e:
        logger.error(f"Error fingerprinting {path}: {e}")
        return None


def init_db(db_url):
    logger.info(f"Initializing database")
    engine = sa.create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    logger.info(f"Database initialized")
    return session()


def process_path(path, session):
    # Collect and sort by creation date
    if not os.path.exists(path):
        logger.info(f"Skipping non-existent path: {path}")
        return

    logger.info(f"Processing path: {path}")
    if path.endswith("/"):
        path = path[:-1]

    if os.path.isfile(path):
        if path.lower().endswith(".flac"):
            logger.info(f"Processing file: {path}")
            msg_id, files = path.split(" ", 1)[0], [path]
        else:
            logger.info(f"Skipping file: {path}")
            return
    else:
        logger.info(f"Processing directory: {path}")
        msg_id, files = path.rsplit("/", 1)[-1].split(" ")[0], (f'{path}/{f}' for f in os.listdir(path) if f.lower().endswith(".flac"))

    for file in files:
        # Skip already indexed
        if session.query(Track).filter_by(path=file).first():
            logger.info(f"Skipping already indexed file: {file}")
            continue

        album, track_number, disc_number = get_metadata(file)
        fp = get_audioprint(file)
        if fp is None:
            logger.info(f"Skipping file without fingerprint: {file}")
            continue

        # Check if the same track already exists
        existing = session.query(Track).filter_by(
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            audioprint=fp
        ).first()

        track = Track(
            message_id=msg_id,
            path=file,
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            audioprint=fp,
            duplicate=existing is not None
        )

        session.add(track)
        session.commit()

        logger.info(f"Processed file: {file}")


def main():
    parser = argparse.ArgumentParser(description="FLAC duplicate checker (ORM + pyacoustid)")
    parser.add_argument("-d","--directory", help="Path to FLAC directory")
    parser.add_argument("--db", "--database", default="sqlite://deduplicate.sqlite", help="Database URL (either SQLite3 or PG DSN")
    args = parser.parse_args()

    session = init_db(args.db)
    process_path(args.directory, session)


if __name__ == "__main__":
    main()
