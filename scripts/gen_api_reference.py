"""Generate docs/02_API_REFERENCE.md from the live route table (method, path, permission, summary).

    python -m scripts.gen_api_reference
"""
from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app
from app.utils.rbac_catalog import ROLES


def _permission(route: APIRoute) -> str:
    for dep in route.dependencies:
        fn = dep.dependency
        cells = getattr(fn, "__closure__", None) or ()
        for cell in cells:
            if isinstance(cell.cell_contents, str) and ":" in cell.cell_contents:
                return cell.cell_contents
    names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
    if "require_superadmin" in names:
        return "platform superadmin"
    if "get_current_user" in names or "get_branch_scope" in names:
        return "authenticated"
    return "public"


def main() -> None:
    rows: dict[str, list[str]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        tag = (route.tags or ["other"])[0]
        perm = _permission(route)
        roles = ", ".join(r for r, (_, _, grants) in ROLES.items() if perm in grants) or "—"
        for method in sorted(route.methods):
            rows.setdefault(tag, []).append(f"| `{method}` | `{route.path}` | `{perm}` | {roles} |")

    out = ["# Stag Fitness API Reference", "",
           "Generated from the running route table by `python -m scripts.gen_api_reference`.",
           "Base URL `/api/v1`. Auth: `Authorization: Bearer <access_token>`; branch: `X-Branch-ID` header",
           "(omitted = home branch, or All Branches for accounts with `branch:switch`). Every response is",
           "`{success, message, data}`; lists add `total, page, page_size`; errors are `{success:false, status_code, message}`.",
           "Interactive docs: `/docs` (Swagger) and `/redoc`.", ""]
    for tag, lines in rows.items():
        out += [f"## {tag}", "", "| Method | Path | Permission | Default roles |", "|---|---|---|---|", *lines, ""]
    target = Path(__file__).resolve().parents[2] / "docs" / "02_API_REFERENCE.md"
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target} ({sum(len(v) for v in rows.values())} operations)")


if __name__ == "__main__":
    main()
