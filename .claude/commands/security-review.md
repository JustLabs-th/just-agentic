Use the security-auditor agent to review the current security posture of the codebase.

Focus on:
1. All 7 defense layers are present and correctly wired in `graph/secure_graph.py`
2. No tool bypasses `@permission_required` in `tools/`
3. `effective_tools(role, dept)` used (not just role alone) everywhere permissions are checked
4. New tools added to `ALL_TOOLS` and covered by RBAC in `security/rbac.py`
5. Output classifier applied to all file-reading tools

Report findings as: Critical / Medium / Low with file:line references.
