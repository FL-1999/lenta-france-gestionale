"""Supplier catalogue and performed services share the existing supplier identity."""
from sqlalchemy import Column, Integer, String, ForeignKey, JSON, Boolean, Date, Numeric
from sqlalchemy.orm import relationship, backref
from .base import Base
from .entities import TimestampMixin


class SupplierService(Base, TimestampMixin):
    __tablename__ = 'supplier_services'
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)


class ServiceRecord(Base, TimestampMixin):
    __tablename__ = 'service_records'
    id = Column(Integer, primary_key=True)
    request_key = Column(String(64), nullable=False, unique=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False, index=True)
    catalogue_id = Column(Integer, ForeignKey('supplier_services.id'), nullable=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), index=True)
    vehicle_id = Column(Integer, ForeignKey('veicoli.id', ondelete='SET NULL'), index=True)
    machine_id = Column(Integer, ForeignKey('machines.id', ondelete='SET NULL'), index=True)
    service_date = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default='planned')
    amount = Column(Numeric(16, 2), nullable=False)
    payload = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    economic_entry_id = Column(Integer, ForeignKey('site_economic_entries.id', ondelete='SET NULL'), unique=True)
    economic_entry = relationship('SiteEconomicEntry', backref=backref('service_record', uselist=False))
