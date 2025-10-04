import argparse
from contextlib import asynccontextmanager
from enum import Enum
from typing import Annotated
import logging

from fastapi import FastAPI, Depends, Response
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Enum as SQLEnum, DateTime, Index, func, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import uvicorn

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level='INFO')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description="Flaczkownia dedup")
parser.add_argument("--db", "--database", default="sqlite:///data/dedup.sqlite3",
                    help="Database URL (eg. sqlite or pgsql path)")
args = parser.parse_args()

global engine
Base = declarative_base()


# ------------------------------------------------------------------------------
# Database Dependency
# ------------------------------------------------------------------------------

def get_session():
    with sessionmaker(bind=engine)() as session:
        yield session


# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------

class Status(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class Queue(Base):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False)
    status = Column(SQLEnum(Status), nullable=False, default=Status.PENDING)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_path", "path", unique=True),
    )


# ------------------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------------------

class Deduplicate(BaseModel):
    msg_id: int
    chat_id: int
    sender_id: int
    fname: str

    mimetype: str
    size: int

    voice: bool
    video: bool

    fwd_sender_id: int | None = None
    reply_to_msg_id: int | None = None
    reply_to_sender_id: int | None = None


# ------------------------------------------------------------------------------
# Lifespan (modern replacement for startup/shutdown events)
# ------------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info(f"Initializing database")
    global engine
    engine = create_engine(args.db, echo=False)
    Base.metadata.create_all(engine)
    logger.info(f"Database initialized")
    yield
    # Shutdown logic
    engine.dispose()


# ------------------------------------------------------------------------------
# FastAPI App
# ------------------------------------------------------------------------------

app = FastAPI(
    root_path="/api/v1",
    debug=False,
    lifespan=lifespan,
)


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------

@app.post(
    path="/dedup"
)
async def dedup(data: Deduplicate, response: Response, session: Annotated[sessionmaker, Depends(get_session)]):
    q = Queue(path=data.fname)
    session.add(q)
    session.commit()

    response.status_code = 204
    return None


# ------------------------------------------------------------------------------
# Run with: uvicorn main:app --reload
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
