"""Shared logistics identities; existing asset records and their foreign keys stay intact."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Boolean, UniqueConstraint
from .base import Base


class FleetPosition(Base):
    __tablename__ = 'fleet_positions'
    asset_key = Column(String(80), primary_key=True)
    place = Column(String(80), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FleetJourney(Base):
    __tablename__ = 'fleet_journeys'
    trip_id = Column(Integer, ForeignKey('trasporti_viaggi.id'), primary_key=True)
    token = Column(String(64), unique=True, nullable=False)
    route = Column(JSON, nullable=False)
    current_stop = Column(Integer, default=0, nullable=False)
    revision = Column(Integer, default=0, nullable=False)
    finished = Column(Boolean, default=False, nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)


class FleetLoad(Base):
    __tablename__ = 'fleet_loads'
    __table_args__ = (UniqueConstraint('trip_id', 'asset_key', name='uq_fleet_trip_asset'),)
    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey('trasporti_viaggi.id'), nullable=False, index=True)
    asset_key = Column(String(80), nullable=False)
    # Nullable unique reservation also protects concurrent planning of the same asset.
    reservation = Column(String(80), unique=True, nullable=True)
    origin = Column(String(80), nullable=False)
    destination = Column(String(80), nullable=False)
    pickup = Column(Integer, nullable=False)
    delivery = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False)
    state = Column(String(30), default='planned', nullable=False)
    technical_state = Column(String(80), nullable=True)


class FleetOperation(Base):
    __tablename__ = 'fleet_operations'
    id = Column(Integer, primary_key=True)
    load_id = Column(Integer, ForeignKey('fleet_loads.id'), nullable=False, index=True)
    stop = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    result = Column(String(20), default='pending', nullable=False)
    reason = Column(String(500), nullable=True)
    before = Column(JSON, nullable=True)


class FleetEvent(Base):
    __tablename__ = 'fleet_events'
    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey('trasporti_viaggi.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    text = Column(String(1000), nullable=False)
