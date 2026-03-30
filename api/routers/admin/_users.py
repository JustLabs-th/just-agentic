"""
User management.

Endpoints (prefix /api/admin):
  GET    /users                — list all users
  POST   /users                — create user with hashed password
  PATCH  /users/{user_id}      — update role, department, active state, or password
"""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_admin
from api.schemas import UserCreate, UserUpdate, UserResponse
from db.models import User, Role, Department
from db.session import get_db
from security.jwt_auth import UserContext
from security.password import hash_password
from security.rbac import effective_clearance

router = APIRouter()


@router.get("/users", response_model=list[UserResponse])
def list_users(admin: UserContext = Depends(require_admin)):
    with get_db() as db:
        users = db.query(User).order_by(User.user_id).all()
        return [_user_to_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate, admin: UserContext = Depends(require_admin)):
    if not body.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    with get_db() as db:
        if db.query(User).filter_by(user_id=body.user_id).first():
            raise HTTPException(status_code=409, detail=f"User '{body.user_id}' already exists")

        role = db.query(Role).filter_by(name=body.role).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"Role '{body.role}' not found")
        dept = db.query(Department).filter_by(name=body.department).first()
        if not dept:
            raise HTTPException(status_code=400, detail=f"Department '{body.department}' not found")

        user = User(
            user_id=body.user_id.strip(),
            hashed_password=hash_password(body.password),
            role_id=role.id,
            department_id=dept.id,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        return _user_to_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    body: UserUpdate,
    admin: UserContext = Depends(require_admin),
):
    with get_db() as db:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")

        if body.role is not None:
            role = db.query(Role).filter_by(name=body.role).first()
            if not role:
                raise HTTPException(status_code=400, detail=f"Role '{body.role}' not found")
            user.role_id = role.id

        if body.department is not None:
            dept = db.query(Department).filter_by(name=body.department).first()
            if not dept:
                raise HTTPException(status_code=400, detail=f"Department '{body.department}' not found")
            user.department_id = dept.id

        if body.is_active is not None:
            user.is_active = body.is_active

        if body.password is not None:
            if len(body.password) < 8:
                raise HTTPException(status_code=400, detail="password must be at least 8 characters")
            user.hashed_password = hash_password(body.password)

        db.flush()
        db.refresh(user)
        return _user_to_response(user)


# ── Helper ────────────────────────────────────────────────────────────────────

def _user_to_response(user: User) -> UserResponse:
    role_name = user.role.name
    dept_name = user.department.name
    return UserResponse(
        id=user.id,
        user_id=user.user_id,
        role=role_name,
        department=dept_name,
        clearance_level=effective_clearance(role_name, dept_name),
        is_active=user.is_active,
        created_at=user.created_at,
    )
