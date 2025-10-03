import argparse
import logging
import os
from typing import Tuple

import acoustid
import sqlalchemy as sa
from mediafile import MediaFile
from sqlalchemy.orm import sessionmaker

Base = sa.orm.declarative_base()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='DEBUG')
logger = logging.getLogger(__name__)

class Track(Base):
    __tablename__ = "tracks"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    message_id = sa.Column(sa.Integer, nullable=False)
    path = sa.Column(sa.String, unique=True, nullable=False)
    track_number = sa.Column(sa.Integer, nullable=True)
    disc_number = sa.Column(sa.Integer, nullable=True)
    album = sa.Column(sa.String, nullable=True)
    acoustid = sa.Column(sa.String, nullable=True)
    duplicate = sa.Column(sa.Boolean, default=False)


def get_metadata(path) -> Tuple[str, int, int]:
    mf = MediaFile(path)
    album = mf.album or ""
    track_number = mf.track or 0
    disc_number = mf.disc or 1
    return album, track_number, disc_number


def get_acoustid(path) -> str | None:
    """Use pyacoustid to calculate Chromaprint fingerprint locally (no API)."""
    try:
        _, fp = acoustid.fingerprint_file(path)
        return fp.decode()  # raw fingerprint string
    except Exception as e:
        logger.error(f"Error fingerprinting {path}: {e}")
        return None


def init_db(db_url):
    logger.debug(f"Initializing database")
    engine = sa.create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    logger.debug(f"Database initialized")
    return session()


def process_path(path, session):
    # Collect and sort by creation date
    if not os.path.exists(path):
        logger.debug(f"Skipping non-existent path: {path}")
        return

    logger.debug(f"Processing path: {path}")
    if path.endswith("/"):
        path = path[:-1]

    if os.path.isfile(path):
        if path.lower().endswith(".flac"):
            logger.debug(f"Processing file: {path}")
            msg_id, files = path.split(" ", 1)[0], [path]
        else:
            logger.debug(f"Skipping file: {path}")
            return
    else:
        logger.debug(f"Processing directory: {path}")
        msg_id, files = path.rsplit("/", 1)[-1].split(" ")[0], (f'{path}/{f}' for f in os.listdir(path) if f.lower().endswith(".flac"))

    for file in files:
        # Skip already indexed
        if session.query(Track).filter_by(path=file).first():
            logger.debug(f"Skipping already indexed file: {file}")
            continue

        album, track_number, disc_number = get_metadata(file)
        fp = get_acoustid(file)
        if fp is None:
            logger.debug(f"Skipping file without fingerprint: {file}")
            continue

        # Check if the same track already exists
        existing = session.query(Track).filter_by(
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            acoustid=fp
        ).first()

        track = Track(
            message_id=msg_id,
            path=file,
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            acoustid=fp,
            duplicate=existing is not None
        )

        session.add(track)
        session.commit()

        logger.debug(f"Processed file: {file}")


def main():
    parser = argparse.ArgumentParser(description="FLAC duplicate checker (ORM + pyacoustid)")
    parser.add_argument("-d","--directory", help="Path to FLAC directory")
    parser.add_argument("--db", "--database", default="sqlite://deduplicate.sqlite", help="Database URL (either SQLite3 or PG DSN")
    args = parser.parse_args()

    session = init_db(args.db)
    process_path(args.directory, session)


if __name__ == "__main__":
    main()
