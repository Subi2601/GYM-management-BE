"""
RBACEngine — permission enforcement.
DB-only implementation: always queries PostgreSQL directly, no cache.
Single-tenant: one permission path via user_roles.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RBACEngine:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Permission check ──────────────────────────────────────────────────────

    async def has_permission(self, user_id: UUID, code: str) -> bool:
        """Check whether the user holds the permission code via user_roles."""
        perms = await self._load_perms(user_id)
        return code in perms

    async def _load_perms(self, user_id: UUID) -> set[str]:
        rows = await self._db.execute(
            text("""
                SELECT DISTINCT p.code
                FROM   rbac_user_roles       ur
                JOIN   rbac_roles            r  ON r.id  = ur.role_id
                JOIN   rbac_role_permissions rp ON rp.role_id = r.id
                JOIN   rbac_permissions      p  ON p.id  = rp.permission_id
                WHERE  ur.user_id    = :uid
                  AND  ur.is_active  = true
                  AND  r.deleted_at  IS NULL
                  AND  rp.deleted_at IS NULL
                  AND  p.deleted_at  IS NULL
                  AND  ur.deleted_at IS NULL
                  AND  rp.is_granted = true
            """),
            {"uid": str(user_id)},
        )
        return {r[0] for r in rows.fetchall()}

    # ── User access tree (roles + modules → screens → permissions) ───────────

    async def get_user_access(self, user_id: UUID) -> dict:
        """
        Returns the full access tree for a user.
        Response shape:
          {
            "roles": [{"id", "name", "code"}],
            "access": [{"module_id", "module_name", "module_code", "module_icon",
                        "sort_order", "screens": [{"screen_id", "screen_name",
                        "screen_code", "screen_route", "permissions":
                        [{"id", "name", "code"}]}]}]
          }
        """
        rows = await self._db.execute(
            text("""
                SELECT
                    r.id          AS role_id,
                    r.name        AS role_name,
                    r.code        AS role_code,
                    m.id          AS module_id,
                    m.name        AS module_name,
                    m.code        AS module_code,
                    m.icon        AS module_icon,
                    m.sort_order  AS module_sort_order,
                    s.id          AS screen_id,
                    s.name        AS screen_name,
                    s.code        AS screen_code,
                    s.route_path  AS screen_route,
                    s.sort_order  AS screen_sort_order,
                    p.id          AS permission_id,
                    p.name        AS permission_name,
                    p.code        AS permission_code
                FROM   rbac_user_roles       ur
                JOIN   rbac_roles            r  ON r.id  = ur.role_id
                JOIN   rbac_role_permissions rp ON rp.role_id = r.id
                JOIN   rbac_permissions      p  ON p.id  = rp.permission_id
                JOIN   rbac_screens          s  ON s.id  = p.screen_id
                JOIN   rbac_modules          m  ON m.id  = s.module_id
                WHERE  ur.user_id    = :uid
                  AND  ur.is_active  = true
                  AND  ur.deleted_at IS NULL
                  AND  r.deleted_at  IS NULL
                  AND  rp.is_granted = true
                  AND  rp.deleted_at IS NULL
                  AND  p.deleted_at  IS NULL
                  AND  s.deleted_at  IS NULL
                  AND  m.deleted_at  IS NULL
                ORDER BY m.sort_order, s.sort_order, p.code
            """),
            {"uid": str(user_id)},
        )
        return self._build_access_tree(rows.fetchall())

    @staticmethod
    def _build_access_tree(rows) -> dict:
        """
        Groups flat SQL rows into:
          { roles: [...], access: [ module → screens → permissions ] }
        Permissions are deduplicated across roles.
        """
        from collections import OrderedDict

        roles: dict = {}
        modules: dict = OrderedDict()

        for row in rows:
            # ── Roles (unique by id) ──────────────────────────────────────────
            role_key = str(row.role_id)
            if role_key not in roles:
                roles[role_key] = {
                    "id":   role_key,
                    "name": row.role_name,
                    "code": row.role_code,
                }

            # ── Modules ───────────────────────────────────────────────────────
            mod_key = str(row.module_id)
            if mod_key not in modules:
                modules[mod_key] = {
                    "module_id":   mod_key,
                    "module_name": row.module_name,
                    "module_code": row.module_code,
                    "module_icon": row.module_icon,
                    "sort_order":  row.module_sort_order,
                    "screens":     OrderedDict(),
                }

            # ── Screens ───────────────────────────────────────────────────────
            scr_key = str(row.screen_id)
            if scr_key not in modules[mod_key]["screens"]:
                modules[mod_key]["screens"][scr_key] = {
                    "screen_id":    scr_key,
                    "screen_name":  row.screen_name,
                    "screen_code":  row.screen_code,
                    "screen_route": row.screen_route,
                    "permissions":  [],
                    "_perm_seen":   set(),   # deduplicate across roles
                }

            # ── Permissions (deduplicated) ────────────────────────────────────
            scr = modules[mod_key]["screens"][scr_key]
            perm_code = row.permission_code
            if perm_code not in scr["_perm_seen"]:
                scr["_perm_seen"].add(perm_code)
                scr["permissions"].append({
                    "id":   str(row.permission_id),
                    "name": row.permission_name,
                    "code": perm_code,
                })

        # ── Serialise (remove internal dedup sets) ────────────────────────────
        access = []
        for mod in modules.values():
            screens = []
            for scr in mod["screens"].values():
                scr.pop("_perm_seen")
                screens.append(scr)
            mod["screens"] = screens
            access.append(mod)

        return {"roles": list(roles.values()), "access": access}

    async def invalidate(self, user_id: UUID) -> None:
        """No-op — no cache to invalidate."""
        pass
