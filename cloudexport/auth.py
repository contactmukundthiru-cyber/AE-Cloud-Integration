from datetime import datetime, timedelta
from typing import Optional
import secrets
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .config import settings
from .models import User

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')


def hash_api_key(api_key: str) -> str:
    return pwd_context.hash(api_key)


def verify_api_key(api_key: str, hashed: str) -> bool:
    return pwd_context.verify(api_key, hashed)


def create_access_token(subject: str) -> str:
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.utcnow() + expires_delta
    payload = {'sub': subject, 'exp': expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def bootstrap_admin(session: Session) -> User:
    user = session.query(User).filter(User.email == settings.bootstrap_admin_email).one_or_none()
    if user:
        return user
    api_key = settings.bootstrap_api_key or secrets.token_urlsafe(32)
    user = User(
        email=settings.bootstrap_admin_email,
        api_key_hash=hash_api_key(api_key),
        api_key_hint=api_key[-6:],
        is_admin=True
    )
    session.add(user)
    session.commit()
    return user


def authenticate_api_key(session: Session, api_key: str) -> Optional[User]:
    user = session.query(User).filter(User.is_active.is_(True)).all()
    for candidate in user:
        if verify_api_key(api_key, candidate.api_key_hash):
            return candidate
    return None
