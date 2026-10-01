"""Independent, versioned general work map. Wall plans and fiches remain authoritative."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, LargeBinary, Text, DateTime
from sqlalchemy.orm import relationship, backref, deferred
from .base import Base


class SiteWorksMap(Base):
    __tablename__ = 'site_works_maps'
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), primary_key=True)
    revision = Column(Integer, nullable=False, default=1)
    payload = Column(Text, nullable=False)
    # Freeze the approved reference: a later wall PDF must not move installed works.
    reference = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    site = relationship('Site', backref=backref('works_map', uselist=False, cascade='all, delete-orphan'))


class SiteStrutDrawing(Base):
    __tablename__ = 'site_strut_drawings'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    page_number = Column(Integer, nullable=False)
    pdf_data = deferred(Column(LargeBinary, nullable=False))
    preview_data = deferred(Column(LargeBinary, nullable=False))
    proposal = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    site = relationship('Site', backref=backref('strut_drawings', cascade='all, delete-orphan'))
