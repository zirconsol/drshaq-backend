from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import authenticate_user, create_access_token
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserRead

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Credenciales invalidas')
    token, expires_in = create_access_token(user.username, user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, role=user.role)


@router.get('/me', response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead(id=user.id, username=user.username, role=user.role, is_active=user.is_active)
