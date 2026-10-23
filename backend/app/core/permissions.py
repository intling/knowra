KNOWLEDGE_READ = "knowledge:read"
KNOWLEDGE_WRITE = "knowledge:write"
USERS_MANAGE = "users:manage"
MODELS_MANAGE = "models:manage"
OPERATIONS_READ = "operations:read"
AUDIT_READ = "audit:read"

_ROLE_PERMISSIONS = {
    "viewer": (KNOWLEDGE_READ,),
    "member": (KNOWLEDGE_READ, KNOWLEDGE_WRITE),
    "admin": (
        KNOWLEDGE_READ,
        KNOWLEDGE_WRITE,
        USERS_MANAGE,
        MODELS_MANAGE,
        OPERATIONS_READ,
        AUDIT_READ,
    ),
}


def permissions_for(role: str) -> list[str]:
    return sorted(_ROLE_PERMISSIONS.get(role, ()))
