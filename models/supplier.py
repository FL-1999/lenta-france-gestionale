from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

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
    articoli = relationship(
        "SupplierArticle",
        back_populates="supplier",
        cascade="all, delete-orphan",
        order_by="SupplierArticle.codice",
    )


class SupplierArticle(Base, TimestampMixin):
    """Codice articolo salvato per un fornitore.

    Si popola automaticamente man mano che si creano gli ordini: così i codici
    non vanno ricreati ogni volta, ma restano nel catalogo del fornitore.
    """
    __tablename__ = "supplier_articles"
    __table_args__ = (
        UniqueConstraint("supplier_id", "codice", name="uq_supplier_articles_supplier_codice"),
    )

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    codice = Column(String(100), nullable=False)
    descrizione = Column(Text, nullable=True)
    unita = Column(String(50), nullable=True)
    ultimo_prezzo = Column(Float, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    usi = Column(Integer, nullable=False, default=0)

    supplier = relationship("Supplier", back_populates="articoli")
