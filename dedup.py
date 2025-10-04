import argparse
import logging
import os

import audioprint
import sqlalchemy as sa
from mediafile import MediaFile
from sqlalchemy.orm import sessionmaker

Base = sa.orm.declarative_base()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
logger = logging.getLogger(__name__)


class Track(Base):
    __tablename__ = "tracks"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    path = sa.Column(sa.String, unique=True, nullable=False)
    acoustic_fingerprint = sa.Column(sa.BigInteger, nullable=False)
    album = sa.Column(sa.String)
    disc_number = sa.Column(sa.Integer)
    track_number = sa.Column(sa.Integer)
    duplicate = sa.Column(sa.Boolean, nullable=False, default=False)

    __table_args__ = (
        sa.Index("idx_path", "path", unique=True),
        sa.Index("idx_duplicate", "acoustic_fingerprint", "album", "disc_number", "track_number",
                 unique=True, postgresql_where=duplicate == False, sqlite_where=duplicate == False),
    )


def _recursive_path_walk(path):
    if not os.path.exists(path):
        return
    elif os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for file in files:
                yield os.path.join(root, file)
    else:
        yield path


def process_path(path, session):
    logger.info(f"Processing path: {path}")

    for file in _recursive_path_walk(path):
        logger.info(f"Processing file: {file}")

        # Skip already indexed
        if session.query(Track).filter_by(path=file).first():
            logger.info(f"Skipping already indexed file: {file}")
            continue

        mf = MediaFile(file)
        fp = audioprint.fingerprint_file(file)

        # Check if the same track already exists
        existing = session.query(Track).filter_by(
            acoustic_fingerprint=fp,
            album=mf.album,
            disc_number = mf.disc,
            track_number=mf.track,
        ).first()

        track = Track(
            path=file,
            acoustic_fingerprint=fp,
            album=mf.album,
            disc_number=mf.disc,
            track_number=mf.track,
            duplicate=existing is not None,
        )

        session.add(track)
        session.commit()

        logger.info(f"Processed file: {file}")


def main():
    parser = argparse.ArgumentParser(description="Flaczkownia dedup")
    parser.add_argument("-d", "--directory", help="Path to flaczkownia directory")
    parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                        help="Database URL (eg. sqlite or pgsql path)")
    args = parser.parse_args()

    logger.info(f"Initializing database")
    engine = sa.create_engine(args.db, echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    logger.info(f"Database initialized")

    process_path(args.directory, session)


if __name__ == "__main__":
    main()
