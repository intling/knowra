KNOWLEDGE_READ = "knowledge:read"
KNOWLEDGE_WRITE = "knowledge:write"
USERS_MANAGE = "users:manage"
MODELS_MANAGE = "models:manage"

_ROLE_PERMISSIONS = {
    "viewer": (KNOWLEDGE_READ,),
    "member": (KNOWLEDGE_READ, KNOWLEDGE_WRITE),
    "admin": (KNOWLEDGE_READ, KNOWLEDGE_WRITE, USERS_MANAGE, MODELS_MANAGE),
}


def permissions_for(role: str) -> list[str]:
    return sorted(_ROLE_PERMISSIONS.get(role, ()))
