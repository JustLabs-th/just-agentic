from fastapi import APIRouter, HTTPException
from api.schemas import LoginRequest, LoginResponse
from security.jwt_auth import decode_token, make_dev_token
from security.rbac import get_policy, get_department_policy, effective_clearance, effective_tools

router = APIRouter()


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
        raise HTTPException(status_code=400, detail="mode must be 'jwt' or 'dev'")
