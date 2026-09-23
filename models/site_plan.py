"""Original drawings and independently saved draft/approved panel layouts."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, LargeBinary, Text, DateTime
from sqlalchemy.orm import relationship, backref, deferred
from .base import Base


class SitePlan(Base):
    __tablename__ = 'site_plans'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    pdf_data = deferred(Column(LargeBinary, nullable=False))
    preview_data = deferred(Column(LargeBinary, nullable=False))
    page_number = Column(Integer, nullable=False, default=1)
    draft = Column(Text, nullable=False)
    approved = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    approved_revision = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    removed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_by_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    site = relationship('Site', backref=backref('plans', cascade='all, delete-orphan'))
