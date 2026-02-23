from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base
from .entities import TimestampMixin


class Depot(Base, TimestampMixin):
    __tablename__ = "depots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    address = Column(String(255), nullable=False)
    city = Column(String(120), nullable=True)
    zip_code = Column(String(20), nullable=True)
    province = Column(String(120), nullable=True)
    country = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    deliveries = relationship("PurchaseDelivery", back_populates="delivery_depot")
