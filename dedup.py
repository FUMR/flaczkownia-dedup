import argparse
import logging
import os

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
    path = sa.Column(sa.String, unique=True, nullable=False)
    acoustic_fingerprint = sa.Column(sa.Integer, nullable=False)
    album = sa.Column(sa.String, nullable=False)
    disc_number = sa.Column(sa.Integer, nullable=False)
    track_number = sa.Column(sa.Integer, nullable=False)
    duplicate = sa.Column(sa.Boolean, default=False)

    # TODO: uniq tuple


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
            # TODO: NO FUCKING WAY
            msg_id, files = path.split(" ", 1)[0], [path]
        else:
            logger.info(f"Skipping file: {path}")
            return
    else:
        logger.info(f"Processing directory: {path}")
        # TODO: NO FUCKING WAY
        msg_id, files = path.rsplit("/", 1)[-1].split(" ")[0], (f'{path}/{f}' for f in os.listdir(path) if
                                                                f.lower().endswith(".flac"))

    for file in files:
        # Skip already indexed
        if session.query(Track).filter_by(path=file).first():
            logger.info(f"Skipping already indexed file: {file}")
            continue

        mf = MediaFile(path)
        fp = get_audioprint(file)

        # Check if the same track already exists
        existing = session.query(Track).filter_by(
            album=mf.album,
            track_number=mf.track,
            disc_number=mf.disc,
            acoustic_fingerprint=fp
        ).first()

        track = Track(
            path=file,
            album=mf.album,
            track_number=mf.track,
            disc_number=mf.disc,
            acoustic_fingerprint=fp,
            duplicate=existing is not None
        )

        session.add(track)
        session.commit()

        logger.info(f"Processed file: {file}")


def main():
    parser = argparse.ArgumentParser(description="Flaczkownia duplicate remover")
    parser.add_argument("-d", "--directory", help="Path to FLAC directory")
    parser.add_argument("--db", "--database", default="sqlite:///dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    args = parser.parse_args()

    session = init_db(args.db)
    process_path(args.directory, session)


if __name__ == "__main__":
    main()
