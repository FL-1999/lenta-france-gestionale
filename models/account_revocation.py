from sqlalchemy import Column, String, Float
from .base import Base


class AccountRevocation(Base):
    """Prevent old sessions from authenticating an account recreated with the same email."""
    __tablename__ = 'account_revocations'
    email = Column(String(255), primary_key=True)
    revoked_at = Column(Float, nullable=False)
