"""Independent copies: deliberately no cascading references to business records."""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred
from .base import Base


class CloudAsset(Base):
    __tablename__ = "cloud_assets"
    id = Column(Integer, primary_key=True)
    source_key = Column(String(220), unique=True, nullable=False)
    kind = Column(String(40), nullable=False, index=True)
    source_id = Column(String(80), nullable=False)
    site_id = Column(Integer, nullable=True)
    filename = Column(String(300), nullable=False)
    content_type = Column(String(150), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    payload = deferred(Column(LargeBinary, nullable=False))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt = Column(DateTime, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    lease_token = Column(String(40), nullable=True)
    error_code = Column(String(80), nullable=True)
    drive_id = Column(String(250), nullable=True)
    item_id = Column(String(250), nullable=True)
    remote_path = Column(String(500), nullable=True)
    verified_at = Column(DateTime, nullable=True)


class CloudRun(Base):
    __tablename__ = "cloud_runs"
    id = Column(Integer, primary_key=True)
    kind = Column(String(30), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    details = Column(Text, nullable=True)
