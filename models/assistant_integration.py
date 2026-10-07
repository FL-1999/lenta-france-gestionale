"""Additive integration metadata; no schema changes to business tables."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from .base import Base


class AssistantProposal(Base):
    __tablename__ = 'assistant_proposals'
    __table_args__ = (UniqueConstraint('owner_id', 'request_id', name='uq_assistant_request'),)
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    credential_hash = Column(String(64), nullable=False)
    request_id = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)
    summary = Column(JSON, nullable=False)
    summary_hash = Column(String(64), nullable=False)
    state = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    result = Column(JSON, nullable=True)


class AssistantRateBucket(Base):
    __tablename__ = 'assistant_rate_buckets'
    key = Column(String(100), primary_key=True)
    window = Column(Integer, nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
