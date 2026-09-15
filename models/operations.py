"""Additive operational records; existing reports and attendance stay separate."""
from datetime import datetime
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from .base import Base


class ReportDraft(Base):
    __tablename__ = "report_drafts"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    payload = Column(Text, nullable=False, default="{}")
    revision = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    submitted_revision = Column(Integer, nullable=True)
    submitted_report_id = Column(Integer, ForeignKey("reports.id", ondelete="SET NULL"), nullable=True)


class ReportReview(Base):
    __tablename__ = "report_reviews"
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(30), nullable=False, default="submitted")
    version = Column(Integer, nullable=False, default=1)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    note = Column(Text, nullable=True)


class ReportReviewEvent(Base):
    __tablename__ = "report_review_events"
    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ResourcePlan(Base):
    __tablename__ = "resource_plans"
    __table_args__ = (UniqueConstraint("day", "resource_type", "resource_id", name="uq_resource_plan_day"),)
    id = Column(Integer, primary_key=True)
    day = Column(Date, nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    resource_type = Column(String(30), nullable=False)
    resource_id = Column(Integer, nullable=False)
    resource_label = Column(String(300), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("root_id", "number", name="uq_document_revision"),)
    document_id = Column(Integer, ForeignKey("site_documents.id"), primary_key=True)
    root_id = Column(Integer, ForeignKey("site_documents.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    expires_on = Column(Date, nullable=True)
