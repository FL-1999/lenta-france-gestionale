from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base
from .entities import TimestampMixin


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=True)
    legal_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    # Referente (tutti i campi opzionali)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    city = Column(String(120), nullable=True)
    zip_code = Column(String(20), nullable=True)
    province = Column(String(120), nullable=True)
    country = Column(String(120), nullable=True)
    vat_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")
