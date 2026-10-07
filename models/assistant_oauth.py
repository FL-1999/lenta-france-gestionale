"""Private ChatGPT connection metadata; business tables remain untouched."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from .base import Base


class AssistantOAuthClient(Base):
    __tablename__ = 'assistant_oauth_clients'
    id = Column(String(64), primary_key=True)
    redirect_uris = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AssistantOAuthFlow(Base):
    __tablename__ = 'assistant_oauth_flows'
    id = Column(String(64), primary_key=True)
    params = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)


class AssistantOAuthCode(Base):
    __tablename__ = 'assistant_oauth_codes'
    code_hash = Column(String(64), primary_key=True)
    client_id = Column(String(64), nullable=False)
    owner_id = Column(Integer, nullable=False)
    credential_hash = Column(String(64), nullable=False)
    redirect_uri = Column(String(500), nullable=False)
    challenge = Column(String(128), nullable=False)
    scope = Column(String(200), nullable=False)
    resource = Column(String(500), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    grant_id = Column(String(64), nullable=True)


class AssistantOAuthGrant(Base):
    __tablename__ = 'assistant_oauth_grants'
    id = Column(String(64), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    client_id = Column(String(64), nullable=False)
    credential_hash = Column(String(64), nullable=False)
    scope = Column(String(200), nullable=False)
    resource = Column(String(500), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)


class AssistantOAuthToken(Base):
    __tablename__ = 'assistant_oauth_tokens'
    access_hash = Column(String(64), primary_key=True)
    refresh_hash = Column(String(64), nullable=False, unique=True, index=True)
    grant_id = Column(String(64), ForeignKey('assistant_oauth_grants.id'), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    rotated = Column(Boolean, nullable=False, default=False)
