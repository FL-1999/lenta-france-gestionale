from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from .base import Base


class FicheTranslation(Base):
    __tablename__ = 'fiche_report_translations'
    __table_args__ = (UniqueConstraint('fiche_id', 'source_hash', 'language'),)
    id = Column(Integer, primary_key=True)
    fiche_id = Column(Integer, nullable=False, index=True)
    source_hash = Column(String(64), nullable=False)
    language = Column(String(2), nullable=False)
    original = Column(Text, nullable=False)
    translated = Column(Text, nullable=False)
    actor_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
