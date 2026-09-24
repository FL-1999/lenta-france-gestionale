"""Operational cost register. Invoices remain company history after site removal."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship, backref
from .base import Base


class CostContract(Base):
    __tablename__ = 'cost_contracts'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), index=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    payload = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)


class CostDelivery(Base):
    __tablename__ = 'cost_deliveries'
    id = Column(Integer, primary_key=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), index=True)
    site_name = Column(String(255), nullable=False)
    source_key = Column(String(100), nullable=False, unique=True)
    source_snapshot = Column(JSON, nullable=False)
    label = Column(String(255), nullable=False)
    delivery_date = Column(Date, nullable=False)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=True)
    contract = Column(JSON, nullable=False, default=dict)
    reason = Column(String(2000), nullable=False, default='')
    revision = Column(Integer, nullable=False, default=1)
    economic_entry_id = Column(Integer, ForeignKey('site_economic_entries.id', ondelete='SET NULL'), unique=True)
    economic_entry = relationship('SiteEconomicEntry', backref=backref('cost_delivery', uselist=False))
    lines = relationship('CostDeliveryLine', cascade='all, delete-orphan', order_by='CostDeliveryLine.id', back_populates='delivery')


class CostInvoice(Base):
    __tablename__ = 'cost_invoices'
    __table_args__ = (UniqueConstraint('supplier_id', 'number', name='uq_cost_invoice_number'),)
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    number = Column(String(150), nullable=False)
    invoice_date = Column(Date, nullable=False)
    total = Column(Numeric(16, 2), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default='confirmed')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CostDeliveryLine(Base):
    __tablename__ = 'cost_delivery_lines'
    __table_args__ = (
        CheckConstraint('quantity > 0', name='ck_cost_line_quantity'),
        CheckConstraint('unit_price IS NULL OR unit_price >= 0', name='ck_cost_line_price'),
        CheckConstraint('extra >= 0', name='ck_cost_line_extra'),
    )
    id = Column(Integer, primary_key=True)
    delivery_id = Column(Integer, ForeignKey('cost_deliveries.id', ondelete='CASCADE'), nullable=False, index=True)
    delivery = relationship('CostDelivery', back_populates='lines')
    ticket = Column(String(150), nullable=False, default='')
    quantity = Column(Numeric(16, 3), nullable=False)
    unit = Column(String(30), nullable=False, default='m³')
    unit_price = Column(Numeric(16, 4), nullable=True)
    extra = Column(Numeric(16, 2), nullable=False, default=0)
    invoice_id = Column(Integer, ForeignKey('cost_invoices.id'), nullable=True, index=True)
    invoice_quantity = Column(Numeric(16, 3), nullable=True)
    invoice_unit_price = Column(Numeric(16, 4), nullable=True)
    invoice_extra = Column(Numeric(16, 2), nullable=True)
    invoice_reason = Column(String(2000), nullable=True)


class CostSharedExpense(Base):
    __tablename__ = 'cost_shared_expenses'
    id = Column(Integer, primary_key=True)
    request_key = Column(String(64), nullable=False, unique=True)
    description = Column(String(255), nullable=False)
    expense_date = Column(Date, nullable=False)
    total = Column(Numeric(16, 2), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    allocations = relationship('CostAllocation', cascade='all, delete-orphan')


class CostAllocation(Base):
    __tablename__ = 'cost_allocations'
    id = Column(Integer, primary_key=True)
    expense_id = Column(Integer, ForeignKey('cost_shared_expenses.id', ondelete='CASCADE'), nullable=False)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='SET NULL'), nullable=True)
    site_name = Column(String(255), nullable=False)
    amount = Column(Numeric(16, 2), nullable=False)
    economic_entry_id = Column(Integer, ForeignKey('site_economic_entries.id', ondelete='SET NULL'), unique=True)
    economic_entry = relationship('SiteEconomicEntry', backref=backref('cost_allocation', uselist=False))
