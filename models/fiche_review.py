from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from .base import Base


class FicheReviewEvent(Base):
    __tablename__ = 'fiche_review_events'
    id = Column(Integer, primary_key=True)
    fiche_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, nullable=True)
    action = Column(String(30), nullable=False)
    changes = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
