"""Crea el primer usuario administrativo (bootstrap del RBAC).

Uso (única vez, no es una operación diaria del panel):
    python -m scripts.create_admin correo@empresa.com "Nombre Apellido" contraseña [rol]

Roles: superadmin | admin | editor | asesor (por defecto: superadmin si es
el primer usuario de la tabla; si ya existen usuarios se exige rol explícito).
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select

from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import AdminRole, AdminUser
from app.security.auth import create_admin_user


async def _main(argv: list[str]) -> int:
    s = get_settings()
    if len(argv) < 3:
        print(__doc__)
        return 1
    email, name = argv[0].strip().lower(), argv[1].strip()
    password = argv[2]
    role_arg = argv[3].strip() if len(argv) > 3 else None

    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count()).select_from(AdminUser))).scalar() or 0
    if total == 0:
        role = AdminRole.SUPERADMIN
    elif role_arg:
        if role_arg not in {r.value for r in AdminRole}:
            print(f"Rol inválido: {role_arg}. Válidos: {[r.value for r in AdminRole]}")
            return 1
        role = AdminRole(role_arg)
    else:
        print("Ya existen usuarios administrativos: indica el rol explícitamente "
              "(superadmin | admin | editor | asesor).")
        return 1
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        return 1

    try:
        user = await create_admin_user(email, name, password, role)
    except ValueError as e:
        print(f"No se pudo crear: {e}")
        return 1
    print(f"Usuario creado: {user.email} · rol={user.role.value} · id={user.id}")
    print(f"Accede al panel ({s.ADMIN_HOST}:{s.ADMIN_PORT}) e inicia sesión con estas credenciales.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
