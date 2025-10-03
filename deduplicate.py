import os
import argparse
import acoustid
import logger
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from mediafile import MediaFile


Base = sa.orm.declarative_base()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='DEBUG')
logger = logging.getLogger(__name__)

class Track(Base):
    __tablename__ = "tracks"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    path = sa.Column(sa.String, unique=True, nullable=False)
    track_number = sa.Column(sa.Integer, nullable=True)
    disc_number = sa.Column(sa.Integer, nullable=True)
    album = sa.Column(sa.String, nullable=True)
    acoustid = sa.Column(sa.String, nullable=True)
    duplicate = sa.Column(sa.Boolean, default=False)


def get_metadata(path) -> (str, int, int):
    mf = MediaFile(path)
    album = mf.album or ""
    track_number = mf.track or 0
    disc_number = mf.disc or 1
    return album, track_number, disc_number


def get_acoustid(path) -> str:
    """Use pyacoustid to calculate Chromaprint fingerprint locally (no API)."""
    try:
        _, fp = acoustid.fingerprint_file(path)
        return fp  # raw fingerprint string
    except Exception as e:
        logger.error(f"Error fingerprinting {path}: {e}")
        return None


def init_db(db_url):
    engine = sa.create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def process_directory(directory, session):
    # Collect and sort by creation date
    files = []
    for root, _, flist in os.walk(directory):
        for fname in flist:
            if fname.lower().endswith(".flac"):
                path = os.path.join(root, fname)
                try:
                    ctime = os.path.getctime(path)
                except Exception:
                    ctime = 0
                files.append((ctime, path))
    files.sort(key=lambda x: x[0])  # sort oldest → newest

    for _, path in files:
        # Skip already indexed
        if session.query(Track).filter_by(path=path).first():
            continue

        album, track_number, disc_number = get_metadata(path)
        fp = get_acoustid(path)
        if fp is None:
            continue

        # Check if same track already exists
        existing = session.query(Track).filter_by(
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            acoustid=fp
        ).first()

        track = Track(
            path=path,
            album=album,
            track_number=track_number,
            disc_number=disc_number,
            acoustid=fp,
            duplicate=existing is not None
        )

        session.add(track)
        session.commit()

        logger.info(f"{'DUPLICATE' if duplicate else 'NEW'}: {path}")


def main():
    parser = argparse.ArgumentParser(description="FLAC duplicate checker (ORM + pyacoustid)")
    parser.add_argument("-d","--directory", help="Path to FLAC directory")
    parser.add_argument("--db", "--database", default="sqlite://deduplicate.sqlite", help="Database URL (either SQLite3 or PG DSN")
    args = parser.parse_args()

    session = init_db(args.database)
    process_directory(args.directory, session)


if __name__ == "__main__":
    main()
