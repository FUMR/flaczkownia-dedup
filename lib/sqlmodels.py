from enum import Enum

from sqlalchemy import Column, Enum as SQLEnum, Integer, String, DateTime, func, Index, BigInteger, Boolean
from sqlalchemy.orm import DeclarativeBase


class SQLBase(DeclarativeBase):
    pass


class JobStatus(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Queue(SQLBase):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False)
    status = Column(SQLEnum(JobStatus), nullable=False, default=JobStatus.PENDING)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_queue_path", "path"),
    )

    def update_status(self, status: JobStatus, session):
        self.status = status
        self.updated_at = func.now()

        session.commit()


class Track(SQLBase):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, unique=True, nullable=False)
    acoustic_fingerprint = Column(BigInteger, nullable=False)
    album = Column(String)
    mb_albumid = Column(String)
    disc_number = Column(Integer)
    track_number = Column(Integer)
    duplicate = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_track_path", "path", unique=True),
        Index("idx_track_duplicate", "acoustic_fingerprint", "album", "mb_albumid", "disc_number", "track_number",
              unique=True, postgresql_where=duplicate == False, sqlite_where=duplicate == False),
    )


class UnknownFile(SQLBase):
    __tablename__ = "unknown_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, unique=True, nullable=False)

    __table_args__ = (
        Index("idx_unknown_file_path", "path", unique=True),
    )
