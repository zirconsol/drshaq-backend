from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, UserRole

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(subject: str, role: UserRole) -> tuple[str, int]:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {'sub': subject, 'role': role.value, 'exp': expire}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_expire_minutes * 60


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token invalido') from exc


def ensure_seed_users(db: Session) -> None:
    for username, password, role in [
        (settings.admin_seed_username, settings.admin_seed_password, UserRole.admin),
        (settings.editor_seed_username, settings.editor_seed_password, UserRole.editor),
    ]:
        existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if existing:
            continue
        db.add(User(username=username, hashed_password=hash_password(password), role=role, is_active=True))
    db.commit()
