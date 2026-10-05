"""Non-destructive integration smoke tests against a running Publicador backend.

Requires three existing users (ADMIN, OPERATOR A, OPERATOR B) and two
existing TEST products, one created by each operator. Performs no publishing,
editing, or image upload; briefly acquires and releases an edit lease on A's
fixture. Do NOT run against a product actively being edited.
"""

from __future__ import annotations

import argparse
from getpass import getpass
from urllib.parse import urlsplit
from uuid import UUID

import httpx


class CheckFailed(RuntimeError):
    pass


def require_code(response: httpx.Response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise CheckFailed(f"{label}: esperado HTTP {expected}; recibido {response.status_code}")
    print(f"[OK] {label}: HTTP {expected}")


def login(client: httpx.Client, username: str, role: str) -> None:
    password = getpass(f"Contraseña de {username} ({role}): ")
    response = client.post("/api/operator-auth/login", json={"username": username, "password": password})
    require_code(response, 200, f"Login {username}")
    current = client.get("/api/operator-auth/me")
    require_code(current, 200, f"Sesión {username}")
    identity = current.json()
    if identity.get("role") != role or identity.get("username", "").casefold() != username.casefold():
        raise CheckFailed(f"La identidad no coincide con {username} / {role}")


def _uuid(value: str) -> str:
    return str(UUID(value))


def main() -> int:
    parser = argparse.ArgumentParser(description="Comprobación integrada de roles, propiedad y bloqueos")
    parser.add_argument("--base-url", required=True, help="Origen público de la app, sin rutas ni parámetros")
    parser.add_argument("--admin", required=True, help="Usuario ADMIN existente")
    parser.add_argument("--operator-a", required=True, help="Usuario OPERATOR propietario de producto A")
    parser.add_argument("--operator-b", required=True, help="Usuario OPERATOR propietario de producto B")
    parser.add_argument("--product-a", required=True, type=_uuid, help="ID de la ficha de prueba de A")
    parser.add_argument("--product-b", required=True, type=_uuid, help="ID de la ficha de prueba de B")
    parser.add_argument("--batch-a", type=_uuid, help="Lote de prueba de A (opcional)")
    parser.add_argument("--job-a", type=_uuid, help="Job de prueba de A (opcional)")
    parser.add_argument("--image-a", type=_uuid, help="Imagen de ficha A (opcional)")
    args = parser.parse_args()
    origin = args.base_url.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        parser.error("--base-url debe ser solo el origen HTTP(S), sin ruta")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("No enviar credenciales por HTTP fuera de localhost")
    if len({args.admin.casefold(), args.operator_a.casefold(), args.operator_b.casefold()}) != 3:
        parser.error("Usá tres identidades diferentes")
    if args.product_a == args.product_b:
        parser.error("Las dos fichas de prueba deben ser diferentes")

    clients = {name: httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=25,
                                  follow_redirects=False) for name in ("anon", "admin", "a", "b")}
    held: list[tuple[str, str]] = []
    try:
        require_code(clients["anon"].get("/api/accounts"), 401, "Cuentas sin sesión")
        require_code(clients["anon"].get(f"/api/product-edit-leases/{args.product_a}"), 401,
                     "Ficha sin sesión")
        login(clients["admin"], args.admin, "ADMIN")
        login(clients["a"], args.operator_a, "OPERATOR")
        login(clients["b"], args.operator_b, "OPERATOR")
        for who, expected_a, expected_b in (("admin", 200, 200), ("a", 200, 403), ("b", 403, 200)):
            require_code(clients[who].get(f"/api/product-edit-leases/{args.product_a}"), expected_a,
                         f"Ficha A para {who}")
            require_code(clients[who].get(f"/api/product-edit-leases/{args.product_b}"), expected_b,
                         f"Ficha B para {who}")
        require_code(clients["a"].get("/api/operator-users"), 403, "Operador no administra usuarios")
        require_code(clients["admin"].get("/api/operator-users"), 200, "Administrador lista usuarios")
        for value, endpoint in ((args.batch_a, "/api/drafts/batches/{}"),
                                (args.job_a, "/api/jobs/{}"), (args.image_a, "/uploads/{}")):
            if value:
                path = endpoint.format(value)
                require_code(clients["a"].get(path), 200, f"Recurso propio {path}")
                require_code(clients["b"].get(path), 403, f"Recurso ajeno {path}")
                require_code(clients["admin"].get(path), 200, f"Recurso administrador {path}")

        print("[INFO] Comienza prueba de bloqueo sobre ficha A; no debe estar en edición")
        lease_url = f"/api/product-edit-leases/{args.product_a}"
        response = clients["a"].post(lease_url)
        require_code(response, 200, "Operador A adquiere bloqueo")
        token_a = response.json()["fencing_token"]
        held.append(("a", token_a))
        require_code(clients["admin"].post(lease_url), 409,
                     "Administrador no puede tomar bloqueo de otra sesión")
        require_code(clients["a"].put(lease_url, json={"fencing_token": token_a}), 200,
                     "Renovación de bloqueo propio")
        require_code(clients["a"].request("DELETE", lease_url, json={"fencing_token": token_a}), 204,
                     "Liberación por Operador A")
        held.pop()
        response = clients["admin"].post(lease_url)
        require_code(response, 200, "Administrador adquiere bloqueo liberado")
        token_admin = response.json()["fencing_token"]
        held.append(("admin", token_admin))
        require_code(clients["a"].put(lease_url, json={"fencing_token": token_a}), 409,
                     "Token anterior no puede renovar")
        require_code(clients["admin"].request("DELETE", lease_url, json={"fencing_token": token_admin}), 204,
                     "Liberación del Administrador")
        held.pop()
        require_code(clients["a"].post("/api/operator-auth/logout"), 204, "Logout de A")
        require_code(clients["a"].get("/api/operator-auth/me"), 401, "Sesión revocada")
        print("\nRESULTADO: verificaciones ejecutadas sin fallos. No se publicaron ni editaron fichas.")
        return 0
    except (CheckFailed, httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"\n[ERROR] {exc}")
        print("No habilites el acceso general hasta resolver la discrepancia.")
        return 1
    finally:
        for who, token in reversed(held):
            try:
                response = clients[who].request("DELETE", f"/api/product-edit-leases/{args.product_a}",
                                                 json={"fencing_token": token})
                print(f"[LIMPIEZA] Liberación del bloqueo pendiente: HTTP {response.status_code}")
            except httpx.HTTPError:
                print("[AVISO] No se pudo liberar el bloqueo: caducará según su TTL")
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
