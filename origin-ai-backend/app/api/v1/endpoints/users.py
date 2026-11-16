"""Authenticated user profile API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import ProfileUpdateRequest, UserResponse


router = APIRouter(prefix="/users")


@router.get("/me", response_model=UserResponse, summary="Get the current user's profile")
def get_my_profile(user: User = Depends(get_current_user)):
    return user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the current user's profile",
)
def update_my_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude_unset=True)
    if "full_name" in updates:
        user.full_name = updates["full_name"]
    if "profile_picture" in updates:
        user.profile_picture = updates["profile_picture"]
    db.commit()
    db.refresh(user)
    return user


__all__ = ["router"]
