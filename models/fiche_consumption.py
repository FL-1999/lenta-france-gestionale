from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from .base import Base


class FicheConsumptionAlert(Base):
    """Current consumption decision; the audit history lives in FicheReviewEvent."""
    __tablename__ = 'fiche_consumption_alerts'
    fiche_id = Column(Integer, ForeignKey('fiches.id', ondelete='CASCADE'), primary_key=True)
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False)  # pending / validated / resolved
    validated_by_id = Column(Integer, nullable=True)
    validated_by_name = Column(String(255), nullable=True)
    validated_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
