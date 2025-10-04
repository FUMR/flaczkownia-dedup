from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Index, Integer, String, func

from .sqlbase import SQLBase


class Status(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Queue(SQLBase):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False)
    status = Column(SQLEnum(Status), nullable=False, default=Status.PENDING)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_path", "path"),
    )

    def update_status(self, status: Status, session):
        self.status = status
        self.updated_at = func.now()

        session.commit()
