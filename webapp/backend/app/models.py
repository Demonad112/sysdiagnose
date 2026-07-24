import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class UploadBatch(Base):
    """One upload flow: either a single .tar.gz archive, or a set of files from a folder picker."""

    __tablename__ = "upload_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    mode: Mapped[str] = mapped_column(String(16))  # "archive" | "folder"
    status: Mapped[str] = mapped_column(String(16), default="uploading")  # uploading|assembling|ready|error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    items: Mapped[list["UploadItem"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class UploadItem(Base):
    """A single file within an upload batch, split into chunks for resumable transfer."""

    __tablename__ = "upload_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("upload_batches.id"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(Integer)
    chunk_size: Mapped[int] = mapped_column(Integer)
    total_chunks: Mapped[int] = mapped_column(Integer)
    received_chunks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|uploading|assembled|error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["UploadBatch"] = relationship(back_populates="items")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # matches sysdiagnose case_id
    display_name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_upload_batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_path: Mapped[str] = mapped_column(String(2048), default="")
    ios_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|processing|ready|error

    jobs: Mapped[list["Job"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    completed_steps: Mapped[int] = mapped_column(Integer, default=0)

    case: Mapped["Case"] = relationship(back_populates="jobs")
    steps: Mapped[list["ParserProgress"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ParserProgress(Base):
    """Progress/result of a single parser or analyser run, within a job."""

    __tablename__ = "parser_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(String(16))  # "parser" | "analyser"
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|success|error|skipped
    num_events: Mapped[int] = mapped_column(Integer, default=0)
    num_errors: Mapped[int] = mapped_column(Integer, default=0)
    num_warnings: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="steps")
