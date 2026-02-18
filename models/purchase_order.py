from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import relationship

from .base import Base
from .entities import DeliveryTypeEnum, EmailLanguageEnum


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint("delivery_type IN ('SITE', 'DEPOT', 'PICKUP')", name="ck_purchase_orders_delivery_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(50), nullable=False, unique=True)
    supplier_name = Column(String(255), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier_email = Column(String(255), nullable=True)
    supplier_phone = Column(String(100), nullable=True)
    contact_name = Column(String(255), nullable=True)
    recipient_email = Column(String(255), nullable=True)
    order_date = Column(Date, nullable=True)
    requester_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=True)
    contact_name_override = Column(String(255), nullable=True)
    contact_email_override = Column(String(255), nullable=True)
    email_language = Column(Enum(EmailLanguageEnum), nullable=True)
    order_kind = Column(String(20), nullable=False, default="warehouse")
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    warehouse_category_id = Column(Integer, ForeignKey("magazzino_categorie.id"), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(Date, nullable=True)
    file_invoice = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    delivery_type = Column(String(10), nullable=False, default=DeliveryTypeEnum.PICKUP.value)
    delivery_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    delivery_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    requester = relationship("User", foreign_keys=[requester_user_id])
    requester_v2 = relationship("User", foreign_keys=[requester_id])
    supplier = relationship("Supplier", back_populates="purchase_orders")
    site = relationship("Site", foreign_keys=[site_id])
    delivery_site = relationship("Site", foreign_keys=[delivery_site_id])
    delivery_depot = relationship("Depot")
    warehouse_category = relationship("MagazzinoCategoria")
    lines = relationship("PurchaseOrderLine", back_populates="order", cascade="all, delete-orphan")
    deliveries = relationship("PurchaseDelivery", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PurchaseOrder id={self.id} order_number={self.order_number}>"


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    magazzino_item_id = Column(Integer, ForeignKey("magazzino_items.id"), nullable=True, index=True)
    description = Column(Text, nullable=True)
    qty_ordered = Column(Float, nullable=False)

    order = relationship("PurchaseOrder", back_populates="lines")
    magazzino_item = relationship("MagazzinoItem")
    delivery_lines = relationship("PurchaseDeliveryLine", back_populates="order_line", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PurchaseOrderLine id={self.id} order_id={self.order_id} qty_ordered={self.qty_ordered}>"


class PurchaseDelivery(Base):
    __tablename__ = "purchase_deliveries"
    __table_args__ = (
        CheckConstraint("delivery_type IN ('SITE', 'DEPOT', 'PICKUP')", name="ck_purchase_deliveries_delivery_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    delivery_number = Column(String(100), nullable=False)
    delivery_date = Column(Date, nullable=True)
    file_delivery = Column(String(255), nullable=True)
    confirmed = Column(Boolean, nullable=False, default=False)
    delivery_type = Column(String(10), nullable=False, default=DeliveryTypeEnum.SITE.value)
    delivery_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    delivery_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("PurchaseOrder", back_populates="deliveries")
    delivery_site = relationship("Site")
    delivery_depot = relationship("Depot", back_populates="deliveries")
    lines = relationship("PurchaseDeliveryLine", back_populates="delivery", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PurchaseDelivery id={self.id} order_id={self.order_id} delivery_number={self.delivery_number}>"


class PurchaseDeliveryLine(Base):
    __tablename__ = "purchase_delivery_lines"

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey("purchase_deliveries.id"), nullable=False)
    order_line_id = Column(Integer, ForeignKey("purchase_order_lines.id"), nullable=False)
    qty_delivered = Column(Float, nullable=False)

    delivery = relationship("PurchaseDelivery", back_populates="lines")
    order_line = relationship("PurchaseOrderLine", back_populates="delivery_lines")

    def __repr__(self) -> str:
        return f"<PurchaseDeliveryLine id={self.id} delivery_id={self.delivery_id} qty_delivered={self.qty_delivered}>"


def _validate_purchase_order_delivery_destination(target: PurchaseOrder) -> None:
    delivery_type = target.delivery_type or DeliveryTypeEnum.PICKUP.value
    target.delivery_type = delivery_type

    if delivery_type == DeliveryTypeEnum.SITE.value:
        if target.delivery_site_id is None:
            raise ValueError("delivery_site_id is required when delivery_type=SITE")
        if target.delivery_depot_id is not None:
            raise ValueError("delivery_depot_id must be NULL when delivery_type=SITE")
    elif delivery_type == DeliveryTypeEnum.DEPOT.value:
        if target.delivery_depot_id is None:
            raise ValueError("delivery_depot_id is required when delivery_type=DEPOT")
        if target.delivery_site_id is not None:
            raise ValueError("delivery_site_id must be NULL when delivery_type=DEPOT")
    elif delivery_type == DeliveryTypeEnum.PICKUP.value:
        if target.delivery_site_id is not None or target.delivery_depot_id is not None:
            raise ValueError("delivery_site_id and delivery_depot_id must be NULL when delivery_type=PICKUP")
    else:
        raise ValueError("delivery_type must be one of SITE, DEPOT, PICKUP")


@event.listens_for(PurchaseOrder, "before_insert")
def _purchase_order_before_insert(_mapper, _connection, target: PurchaseOrder) -> None:
    _validate_purchase_order_delivery_destination(target)


@event.listens_for(PurchaseOrder, "before_update")
def _purchase_order_before_update(_mapper, _connection, target: PurchaseOrder) -> None:
    _validate_purchase_order_delivery_destination(target)
