"""One physical pour, with stable panel identities and auditable allocations."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from .base import Base


class SitePour(Base):
    __tablename__ = 'site_pours'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    label = Column(String(200), nullable=False)
    total_m3 = Column(Float)
    cast_date = Column(Date)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    site = relationship('Site', backref=backref('pours', cascade='all, delete-orphan'))
    members = relationship('SitePourPanel', back_populates='pour', cascade='all, delete-orphan', lazy='selectin', order_by='SitePourPanel.number')


class SitePourPanel(Base):
    __tablename__ = 'site_pour_panels'
    __table_args__ = (UniqueConstraint('site_id', 'number', name='uq_pour_site_panel'),)
    id = Column(Integer, primary_key=True)
    pour_id = Column(Integer, ForeignKey('site_pours.id', ondelete='CASCADE'), nullable=False)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), nullable=False)
    number = Column(Integer, nullable=False)
    label = Column(String(100), nullable=False)
    fiche_id = Column(Integer, ForeignKey('fiches.id', ondelete='SET NULL'))
    snapshot = Column(Text, nullable=False)
    allocated_m3 = Column(Float)
    pour = relationship('SitePour', back_populates='members', lazy='joined')
    fiche = relationship('Fiche', backref=backref('pour_panels', lazy='selectin'))
