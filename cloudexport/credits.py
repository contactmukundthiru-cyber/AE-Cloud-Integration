from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import CreditLedger


@dataclass
class CreditBalance:
    posted_usd: float
    reserved_usd: float
    available_usd: float


def get_balances(db: Session, user_id: str) -> CreditBalance:
    posted = db.query(func.coalesce(func.sum(CreditLedger.amount_usd), 0.0)).filter(
        CreditLedger.user_id == user_id,
        CreditLedger.status == 'posted'
    ).scalar() or 0.0

    reserved = db.query(func.coalesce(func.sum(CreditLedger.amount_usd), 0.0)).filter(
        CreditLedger.user_id == user_id,
        CreditLedger.status == 'reserved'
    ).scalar() or 0.0

    available = posted + reserved
    return CreditBalance(posted_usd=float(posted), reserved_usd=float(reserved), available_usd=float(available))


def reserve_credits(db: Session, user_id: str, job_id: str, amount_usd: float) -> CreditBalance:
    if amount_usd <= 0:
        raise ValueError('Reservation amount must be positive')

    existing = db.query(CreditLedger).filter(
        CreditLedger.user_id == user_id,
        CreditLedger.job_id == job_id,
        CreditLedger.entry_type == 'RESERVE'
    ).one_or_none()

    if existing:
        return get_balances(db, user_id)

    balances = get_balances(db, user_id)
    if balances.available_usd < amount_usd:
        raise ValueError('Insufficient credits')

    entry = CreditLedger(
        user_id=user_id,
        job_id=job_id,
        entry_type='RESERVE',
        status='reserved',
        amount_usd=-amount_usd,
        currency='USD'
    )
    db.add(entry)
    db.commit()
    return get_balances(db, user_id)


def settle_job_credits(db: Session, job_id: str, actual_cost_usd: float) -> None:
    entry = db.query(CreditLedger).filter(
        CreditLedger.job_id == job_id,
        CreditLedger.entry_type == 'RESERVE'
    ).one_or_none()

    if not entry or entry.status != 'reserved':
        return

    reserved = abs(entry.amount_usd)
    balances = get_balances(db, entry.user_id)
    max_charge = max(0.0, balances.available_usd + reserved)
    actual_cost = max(0.0, min(actual_cost_usd, max_charge))

    entry.status = 'posted'
    entry.amount_usd = -actual_cost
    if actual_cost_usd > max_charge:
        entry.details = {
            'reason': 'insufficient_funds',
            'shortfall': round(actual_cost_usd - max_charge, 2)
        }
    db.add(entry)

    if actual_cost < reserved:
        refund = CreditLedger(
            user_id=entry.user_id,
            job_id=job_id,
            entry_type='REFUND',
            status='posted',
            amount_usd=reserved - actual_cost,
            currency='USD',
            details={'reason': 'unused_reservation'}
        )
        db.add(refund)
    elif actual_cost > reserved:
        extra = CreditLedger(
            user_id=entry.user_id,
            job_id=job_id,
            entry_type='SETTLEMENT',
            status='posted',
            amount_usd=-(actual_cost - reserved),
            currency='USD',
            details={'reason': 'overage'}
        )
        db.add(extra)

    db.commit()


def void_reservation(db: Session, job_id: str, reason: str) -> None:
    entry = db.query(CreditLedger).filter(
        CreditLedger.job_id == job_id,
        CreditLedger.entry_type == 'RESERVE'
    ).one_or_none()

    if not entry or entry.status != 'reserved':
        return

    entry.status = 'voided'
    entry.details = {'reason': reason}
    db.add(entry)
    db.commit()


def credit_purchase(db: Session, user_id: str, amount_usd: float, external_id: str, source: str) -> None:
    if external_id:
        existing = db.query(CreditLedger).filter(CreditLedger.external_id == external_id).one_or_none()
        if existing:
            return
    entry = CreditLedger(
        user_id=user_id,
        entry_type='PURCHASE',
        status='posted',
        amount_usd=amount_usd,
        currency='USD',
        external_id=external_id,
        details={'source': source}
    )
    db.add(entry)
    db.commit()


def manual_adjust(db: Session, user_id: str, amount_usd: float, reason: str, external_id: Optional[str] = None) -> None:
    if external_id:
        existing = db.query(CreditLedger).filter(CreditLedger.external_id == external_id).one_or_none()
        if existing:
            return
    entry = CreditLedger(
        user_id=user_id,
        entry_type='ADJUSTMENT',
        status='posted',
        amount_usd=amount_usd,
        currency='USD',
        external_id=external_id,
        details={'reason': reason}
    )
    db.add(entry)
    db.commit()
