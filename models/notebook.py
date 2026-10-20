"""Private notes: a site link never confers document access."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, UniqueConstraint, CheckConstraint
from .base import Base


class NotebookNote(Base):
    __tablename__ = 'notebook_notes'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key', name='uq_notebook_create'),
        CheckConstraint("kind IN ('free', 'meeting', 'list')", name='ck_notebook_kind'),
    )
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    request_key = Column(String(64), nullable=False)
    site_id = Column(Integer, ForeignKey('sites.id'), nullable=True, index=True)
    site_snapshot = Column(JSON, nullable=False, default=dict)
    title = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False, default='free')
    collection = Column(String(100), nullable=False, default='')
    body = Column(Text, nullable=False, default='')
    details = Column(JSON, nullable=False, default=dict)
    archived = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NotebookGrant(Base):
    __tablename__ = 'notebook_grants'
    __table_args__ = (
        UniqueConstraint('note_id', 'user_id', name='uq_notebook_grant'),
        CheckConstraint("permission IN ('read', 'edit')", name='ck_notebook_permission'),
    )
    id = Column(Integer, primary_key=True)
    note_id = Column(Integer, ForeignKey('notebook_notes.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    permission = Column(String(10), nullable=False)


class NotebookRevision(Base):
    """Owner-only original snapshots, never included in shared note responses."""
    __tablename__ = 'notebook_revisions'
    id = Column(Integer, primary_key=True)
    note_id = Column(Integer, ForeignKey('notebook_notes.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NotebookDraft(Base):
    __tablename__ = 'notebook_drafts'
    __table_args__ = (UniqueConstraint('note_id', 'request_key', name='uq_notebook_draft'),)
    id = Column(String(32), primary_key=True)
    note_id = Column(Integer, ForeignKey('notebook_notes.id'), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    request_key = Column(String(64), nullable=False)
    base_version = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False, default='processing')
    mode = Column(String(20), nullable=False)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NotebookAIQuota(Base):
    __tablename__ = 'notebook_ai_quota'
    key = Column(String(80), primary_key=True)
    count = Column(Integer, nullable=False, default=0)


class NotebookExtract(Base):
    """Owner-only navigation between a complete note and confirmed extracts."""
    __tablename__ = 'notebook_extracts'
    __table_args__ = (
        UniqueConstraint('draft_id', 'part_index', name='uq_notebook_extract_part'),
        UniqueConstraint('child_note_id', name='uq_notebook_extract_child'),
    )
    id = Column(Integer, primary_key=True)
    source_note_id = Column(Integer, ForeignKey('notebook_notes.id'), nullable=False, index=True)
    child_note_id = Column(Integer, ForeignKey('notebook_notes.id'), nullable=False)
    draft_id = Column(String(32), ForeignKey('notebook_drafts.id'), nullable=False)
    part_index = Column(Integer, nullable=False)
