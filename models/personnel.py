"""Personnel planning and private communications; attendance remains the shared ledger."""
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, ForeignKey, Text, LargeBinary, UniqueConstraint, CheckConstraint
from .base import Base
from .entities import Personale, PersonalePresenza, TimestampMixin


class PersonnelTeam(Base, TimestampMixin):
    __tablename__ = 'personnel_teams'
    __table_args__ = (CheckConstraint('(site_id IS NULL) != (depot_id IS NULL)', name='ck_team_destination'),)
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    site_id = Column(Integer, ForeignKey('sites.id'), nullable=True, unique=True)
    depot_id = Column(Integer, ForeignKey('depots.id'), nullable=True)
    lead_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    active = Column(Boolean, default=True, nullable=False)


class PersonnelAssignment(Base, TimestampMixin):
    __tablename__ = 'personnel_assignments'
    __table_args__ = (CheckConstraint('end_date IS NULL OR end_date >= start_date', name='ck_assignment_dates'),)
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('personnel_teams.id'), nullable=False, index=True)
    person_id = Column(Integer, ForeignKey(Personale.__table__.c.id), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)


class PersonnelRequest(Base, TimestampMixin):
    __tablename__ = 'personnel_requests'
    __table_args__ = (UniqueConstraint('created_by_id', 'submission_key', name='uq_personnel_submission'),
        CheckConstraint('end_date IS NULL OR end_date >= start_date', name='ck_personnel_request_dates'))
    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey(Personale.__table__.c.id), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    submission_key = Column(String(64), nullable=False)
    kind = Column(String(20), nullable=False)
    reason = Column(String(30), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    note = Column(Text, nullable=False, default='')
    status = Column(String(20), nullable=False)
    classification = Column(String(20), nullable=True)
    response = Column(Text, nullable=False, default='')
    office_note = Column(Text, nullable=False, default='')
    include_weekends = Column(Boolean, nullable=False, default=False)
    original_received = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)


class PersonnelAttachment(Base, TimestampMixin):
    __tablename__ = 'personnel_attachments'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('personnel_requests.id'), nullable=False, unique=True)
    content_type = Column(String(80), nullable=False)
    encrypted_data = Column(LargeBinary, nullable=False)


class PersonnelAttendanceLink(Base):
    __tablename__ = 'personnel_attendance_links'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('personnel_requests.id'), nullable=False, index=True)
    attendance_id = Column(Integer, ForeignKey(PersonalePresenza.__table__.c.id), nullable=False, unique=True)
    snapshot = Column(Text, nullable=False)


class PersonnelEvent(Base):
    __tablename__ = 'personnel_events'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('personnel_requests.id'), nullable=True, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(80), nullable=False)
    details = Column(Text, nullable=False, default='')
    created_at = Column(DateTime, nullable=False)
