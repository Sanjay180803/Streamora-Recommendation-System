import json
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import (
    ContinueWatching,
    Profile,
    User,
    WatchAgain,
    WatchHistory,
    get_db,
)
from security import (
    create_access_token,
    get_current_user,
    get_owned_profile,
    hash_password,
    pwd_context,
)

router = APIRouter()

MAX_PROFILES = 6
MAX_HISTORY_ITEMS = 100
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"

# ── Schemas ───────────────────────────────────────────────────────────────────
def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.match(value):
        raise ValueError("Enter a valid email address")
    return value


class RegisterRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class CreateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color: str = Field(default="#e50914", pattern=COLOR_PATTERN)
    icon: str = Field(default="\U0001F3AC", max_length=8)


class SaveHistoryRequest(BaseModel):
    profile_id: str
    history: list[Any] = Field(max_length=MAX_HISTORY_ITEMS)

def _profile_dict(profile: Profile) -> dict:
    return {"id": profile.id, "name": profile.name, "color": profile.color, "icon": profile.icon}


def _auth_response(user: User, db: Session) -> dict:
    profiles = db.query(Profile).filter(Profile.user_email == user.email).all()
    return {
        "status": "ok",
        "access_token": create_access_token(user.email),
        "token_type": "bearer",
        "email": user.email,
        "name": user.name,
        "profiles": [_profile_dict(p) for p in profiles],
    }


# ── Auth endpoints ────────────────────────────────────────────────────────────
@router.post("/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password),
    )
    db.add(user)
    db.commit()
    return _auth_response(user, db)


@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.strip().lower()).first()
    if user is None:
        # Spend comparable time on unknown emails so response timing does not
        # reveal which accounts exist.
        pwd_context.dummy_verify()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    valid, new_hash = pwd_context.verify_and_update(req.password, user.password_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if new_hash:
        user.password_hash = new_hash
        db.commit()
    return _auth_response(user, db)


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "name": user.name}


# ── Profile endpoints ─────────────────────────────────────────────────────────
@router.get("/profiles")
def get_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = db.query(Profile).filter(Profile.user_email == user.email).all()
    return {"profiles": [_profile_dict(p) for p in profiles]}


@router.post("/profiles/create")
def create_profile(
    req: CreateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Profile).filter(Profile.user_email == user.email).count()
    if existing >= MAX_PROFILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_PROFILES} profiles allowed")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    profile = Profile(
        id=str(uuid.uuid4()),
        user_email=user.email,
        name=name,
        color=req.color,
        icon=req.icon,
    )
    db.add(profile)
    db.commit()
    return _profile_dict(profile)


# ── Watch history endpoints ───────────────────────────────────────────────────
@router.post("/history/save")
def save_history(
    req: SaveHistoryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_profile(req.profile_id, user, db)
    record = db.query(WatchHistory).filter(
        WatchHistory.user_email == user.email,
        WatchHistory.profile_id == req.profile_id,
    ).first()
    if record:
        record.history    = json.dumps(req.history)
        record.updated_at = datetime.utcnow()
    else:
        record = WatchHistory(
            id=str(uuid.uuid4()),
            user_email=user.email,
            profile_id=req.profile_id,
            history=json.dumps(req.history),
        )
        db.add(record)
    db.commit()
    return {"status": "ok"}

@router.get("/history/{profile_id}")
def get_history(
    profile_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_profile(profile_id, user, db)
    record = db.query(WatchHistory).filter(
        WatchHistory.user_email == user.email,
        WatchHistory.profile_id == profile_id,
    ).first()
    history = json.loads(record.history) if record else []
    return {"history": history}

# ── Continue Watching & Watch Again endpoints ─────────────────────────────────
class SaveListRequest(BaseModel):
    profile_id: str
    items: list[Any] = Field(max_length=MAX_HISTORY_ITEMS)


def _save_list(model, req: SaveListRequest, user: User, db: Session) -> dict:
    get_owned_profile(req.profile_id, user, db)
    record = db.query(model).filter(
        model.user_email == user.email,
        model.profile_id == req.profile_id,
    ).first()
    if record:
        record.items      = json.dumps(req.items)
        record.updated_at = datetime.utcnow()
    else:
        record = model(
            id=str(uuid.uuid4()),
            user_email=user.email,
            profile_id=req.profile_id,
            items=json.dumps(req.items),
        )
        db.add(record)
    db.commit()
    return {"status": "ok"}


def _get_list(model, profile_id: str, user: User, db: Session) -> dict:
    get_owned_profile(profile_id, user, db)
    record = db.query(model).filter(
        model.user_email == user.email,
        model.profile_id == profile_id,
    ).first()
    return {"items": json.loads(record.items) if record else []}


@router.post("/continue-watching/save")
def save_continue_watching(
    req: SaveListRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _save_list(ContinueWatching, req, user, db)

@router.get("/continue-watching/{profile_id}")
def get_continue_watching(
    profile_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_list(ContinueWatching, profile_id, user, db)

@router.post("/watch-again/save")
def save_watch_again(
    req: SaveListRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _save_list(WatchAgain, req, user, db)

@router.get("/watch-again/{profile_id}")
def get_watch_again(
    profile_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_list(WatchAgain, profile_id, user, db)

# ── Profile delete and rename ─────────────────────────────────────────────────
class DeleteProfileRequest(BaseModel):
    profile_id: str

class RenameProfileRequest(BaseModel):
    profile_id: str
    new_name: str = Field(min_length=1, max_length=30)

@router.post("/profiles/delete")
def delete_profile(
    req: DeleteProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = get_owned_profile(req.profile_id, user, db)
    # Delete everything stored for the profile, not just its history
    for model in (WatchHistory, ContinueWatching, WatchAgain):
        db.query(model).filter(model.profile_id == profile.id).delete()
    db.delete(profile)
    db.commit()
    return {"status": "ok"}

@router.post("/profiles/rename")
def rename_profile(
    req: RenameProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = get_owned_profile(req.profile_id, user, db)
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    # Check duplicate name
    existing = db.query(Profile).filter(
        Profile.user_email == user.email,
        Profile.name == new_name,
        Profile.id != profile.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A profile with this name already exists")
    profile.name = new_name
    db.commit()
    return {"status": "ok", "name": profile.name}
