from fastapi import APIRouter, HTTPException
from api.schemas import LoginRequest, LoginResponse, SetupRequest
from db.models import User, Role, Department
from db.session import get_db
from security.jwt_auth import decode_token, make_dev_token
from security.password import hash_password, verify_password
from security.rbac import get_policy, get_department_policy, effective_clearance, effective_tools

router = APIRouter()


@router.get("/setup")
def check_setup():
    """Returns needs_setup=True when no users exist (first-run detection)."""
    with get_db() as db:
        return {"needs_setup": db.query(User).count() == 0}


@router.post("/setup", response_model=LoginResponse, status_code=201)
def first_setup(body: SetupRequest):
    """Create the first super-admin. Fails if any user already exists."""
    if not body.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    with get_db() as db:
        if db.query(User).count() > 0:
            raise HTTPException(status_code=400, detail="Setup already completed")

        admin_role = db.query(Role).filter_by(name="admin").first()
        all_dept = db.query(Department).filter_by(name="all").first()
        if not admin_role or not all_dept:
            raise HTTPException(status_code=500, detail="Default RBAC data not seeded yet")

        user = User(
            user_id=body.user_id.strip(),
            hashed_password=hash_password(body.password),
            role_id=admin_role.id,
            department_id=all_dept.id,
            is_active=True,
        )
        db.add(user)

    clearance = effective_clearance("admin", "all")
    tools = list(effective_tools("admin", "all"))
    token = make_dev_token(body.user_id.strip(), "admin", "all")
    return LoginResponse(
        access_token=token,
        user_id=body.user_id.strip(),
        role="admin",
        department="all",
        clearance_level=clearance,
        allowed_tools=tools,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    if body.mode == "jwt":
        if not body.token:
            raise HTTPException(status_code=400, detail="token is required for JWT mode")
        try:
            ctx = decode_token(body.token)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
        tools = list(effective_tools(ctx.role, ctx.department))
        return LoginResponse(
            access_token=body.token,
            user_id=ctx.user_id,
            role=ctx.role,
            department=ctx.department,
            clearance_level=ctx.clearance_level,
            allowed_tools=tools,
        )

    elif body.mode == "credentials":
        if not body.user_id or not body.password:
            raise HTTPException(status_code=400, detail="user_id and password are required")
        with get_db() as db:
            user = db.query(User).filter_by(user_id=body.user_id).first()
            if not user or not user.hashed_password:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            if not user.is_active:
                raise HTTPException(status_code=401, detail="Account is disabled")
            if not verify_password(body.password, user.hashed_password):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # read while session is still open
            user_id_str = user.user_id
            role_name = user.role.name
            dept_name = user.department.name

        clearance = effective_clearance(role_name, dept_name)
        tools = list(effective_tools(role_name, dept_name))
        token = make_dev_token(user_id_str, role_name, dept_name)
        return LoginResponse(
            access_token=token,
            user_id=user_id_str,
            role=role_name,
            department=dept_name,
            clearance_level=clearance,
            allowed_tools=tools,
        )

    elif body.mode == "dev":
        user_id = body.user_id or "anonymous"
        role = body.role or "viewer"
        department = body.department or "all"
        try:
            get_policy(role)
            get_department_policy(department)
        except PermissionError as e:
            raise HTTPException(status_code=400, detail=str(e))
        clearance = effective_clearance(role, department)
        tools = list(effective_tools(role, department))
        token = make_dev_token(user_id, role, department)
        return LoginResponse(
            access_token=token,
            user_id=user_id,
            role=role,
            department=department,
            clearance_level=clearance,
            allowed_tools=tools,
        )

    else:
        raise HTTPException(status_code=400, detail="mode must be 'credentials', 'jwt', or 'dev'")
