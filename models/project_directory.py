from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import relationship
from .base import Base
from .entities import TimestampMixin


class ProjectPartner(Base, TimestampMixin):
    __tablename__ = 'project_partners'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    name_key = Column(String(768), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)
    projects = relationship('ProjectPartnerSite', cascade='all, delete-orphan', back_populates='partner')


class ProjectPartnerSite(Base, TimestampMixin):
    __tablename__ = 'project_partner_sites'
    __table_args__ = (UniqueConstraint('partner_id', 'site_id', name='uq_project_partner_site'),)
    id = Column(Integer, primary_key=True)
    partner_id = Column(Integer, ForeignKey('project_partners.id'), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), nullable=True, index=True)
    snapshot = Column(JSON, nullable=False)
    roles = Column(JSON, nullable=False)
    partner = relationship('ProjectPartner', back_populates='projects')
    site = relationship('Site')
