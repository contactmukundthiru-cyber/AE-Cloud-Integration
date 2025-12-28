import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, ForeignKey, JSON, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = 'users'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False)
    api_key_hash = Column(String(255), nullable=False)
    api_key_hint = Column(String(12), nullable=False)
    is_active = Column(Boolean, default=True)
    monthly_limit_usd = Column(Float, default=200.0)
    per_job_max_usd = Column(Float, default=50.0)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship('Job', back_populates='user')
    usage = relationship('Usage', back_populates='user')
    ledger_entries = relationship('CreditLedger', back_populates='user')


class Job(Base):
    __tablename__ = 'jobs'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    status = Column(String(32), default='CREATED')
    preset = Column(String(32), nullable=False)
    gpu_class = Column(String(32), nullable=False)
    manifest = Column(JSON, nullable=False)
    custom_options = Column(JSON, nullable=True)
    manifest_hash = Column(String(64), nullable=False)
    project_hash = Column(String(64), nullable=False)
    bundle_key = Column(String(512), nullable=False)
    bundle_sha256 = Column(String(64), nullable=False)
    bundle_size_bytes = Column(Integer, nullable=False)
    result_key = Column(String(512), nullable=True)
    output_name = Column(String(255), nullable=False)
    notification_email = Column(String(255), nullable=True)
    cost_estimate_usd = Column(Float, nullable=False)
    cost_final_usd = Column(Float, nullable=True)
    eta_seconds = Column(Integer, nullable=False)
    progress_percent = Column(Float, default=0.0)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    error_message = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, default=False)
    cache_hit = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    user = relationship('User', back_populates='jobs')
    events = relationship('JobEvent', back_populates='job')


class JobEvent(Base):
    __tablename__ = 'job_events'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    event_type = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship('Job', back_populates='events')


class Usage(Base):
    __tablename__ = 'usage'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    month = Column(String(7), nullable=False)
    cost_usd = Column(Float, default=0.0)
    minutes = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='usage')


class CacheEntry(Base):
    __tablename__ = 'cache_entries'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    manifest_hash = Column(String(64), nullable=False)
    preset = Column(String(32), nullable=False)
    result_key = Column(String(512), nullable=False)
    output_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CreditLedger(Base):
    __tablename__ = 'credit_ledger'
    __table_args__ = (
        UniqueConstraint('external_id', name='uq_credit_ledger_external_id'),
        UniqueConstraint('job_id', 'entry_type', name='uq_credit_ledger_job_entry'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    entry_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    amount_usd = Column(Float, nullable=False)
    currency = Column(String(8), default='USD')
    job_id = Column(String(36), nullable=True)
    external_id = Column(String(128), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='ledger_entries')
