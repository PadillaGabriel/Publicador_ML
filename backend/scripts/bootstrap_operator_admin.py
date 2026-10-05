"""Create the first admin. Run locally, never through an unauthenticated HTTP endpoint."""

from getpass import getpass
from sqlalchemy import select

from app.core.db import SessionLocal
from app.identity import OperatorUser
from app.operator_auth import hash_password, normalize_username


def main() -> None:
    username = normalize_username(input("Nombre de usuario administrador: "))
    display_name = input("Nombre para mostrar: ").strip()
    if not username or not display_name or len(username) > 120 or len(display_name) > 160:
        raise SystemExit("Nombre de usuario o nombre para mostrar inválido")
    password = getpass("Contraseña (mínimo 12 caracteres): ")
    if password != getpass("Repetir contraseña: "):
        raise SystemExit("Las contraseñas no coinciden")
    encoded = hash_password(password)
    with SessionLocal.begin() as db:
        # Bootstrapping cannot mint extra administrators once identity has been initialized.
        if db.scalar(select(OperatorUser.id).limit(1)) is not None:
            raise SystemExit("La base de datos ya tiene usuarios. No se permite ejecutar bootstrap nuevamente")
        db.add(OperatorUser(username=username, display_name=display_name, role="ADMIN", password_hash=encoded, active=True))
    print("Administrador inicial creado.")


if __name__ == "__main__":
    main()
