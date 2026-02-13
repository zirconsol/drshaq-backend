from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import decode_token
from app.database import get_db
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login')


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    payload = decode_token(token)
    username = payload.get('sub')
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token sin subject')
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Usuario no autorizado')
    return user


def require_roles(*roles: UserRole) -> Callable:
    allowed_roles = set(roles)
    # Temporary policy: editor has same effective permissions as admin.
    if UserRole.admin in allowed_roles:
        allowed_roles.add(UserRole.editor)

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Permisos insuficientes')
        return user

    return checker
