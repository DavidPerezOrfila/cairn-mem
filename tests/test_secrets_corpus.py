"""Corpus bidireccional del detector de secretos (S20).

TODOS los valores son FALSOS. Tres listas:
  MUST_REJECT : secretos realistas que el detector debe bloquear.
  MUST_ACCEPT : texto legítimo que NO debe bloquear (incluye vocabulario de Oracle EBS).
  KNOWN_GAPS  : indetectables por naturaleza; se documentan, no se exigen.
"""

import pytest

from cairn_mem.store import reject_secrets

MUST_REJECT = [
    # --- ya cubiertos hoy (no deben regresar) ---
    "config AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "password = hunter2",  # 7 chars: una regla ">=8" lo rompería
    "postgres://user:pass@host/db",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
    "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    # --- huecos medidos en la auditoría ---
    "conn scott/tiger@//dbhost:1521/ORCL",
    "jdbc:oracle:thin:apps/Welcome1@dbhost:1521:PROD",
    (
        "DefaultEndpointsProtocol=https;AccountName=x;"
        "AccountKey=abcdEFGH1234abcdEFGH1234abcdEFGH1234abcdEFGH1234abcdEFGH1234abcdEFGH12=="
    ),
    "https://x.blob.core.windows.net/c?sv=2022&sig=Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA%3D",
    "client_secret ~8Q~abcdefghijklmnopqrstuvwxyz1234567890AB",
    "DB_PASS=Welcome1!",
    "pass=Welcome1",
    "pwd=Welcome1",
    "contraseña: Welcome1",
    "clave = Welcome1",
    "FERNET_KEY=ZmRzYWZkc2Fma2xqZmRzYWZkc2Fma2xqZmRzYWZkc2E=",
    "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH",
    "sk_test_abcdefghijklmnop",
    "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXX",
]

MUST_ACCEPT = [
    # --- hoy rechazados por error (falsos positivos medidos) ---
    "Token: el refresh se hace cada 50 min",
    "password: rotar cada 90 días, guardada en Vault",
    "secret: se lee de Key Vault, nunca del .env",
    "api_key = variable de entorno OPENAI_API_KEY",
    "auth_token: header Authorization, ver docs",
    "El campo password = null en la tabla de pruebas",
    # --- ya aceptados hoy (no deben regresar a rechazo) ---
    "usar https://user@host/repo (sin password)",
    "https://github.com/org/repo@v1 y https://unpkg.com/pkg@1.0.0/dist.js",
    "postgres://localhost:5432/db sin credenciales",
    "token budget: 3000 caracteres",
    "Bearer token en el header, formato Bearer <token>",
    # --- vocabulario real de EBS/BD: las "claves" son columnas, no secretos ---
    "clave primaria: inventory_item_id",
    "clave foránea = organization_id hacia mtl_parameters",
    "contraseña: se pide por Key Vault, no se guarda aquí",
    "el attribute11 de mtl_system_items_vl es numérico como texto",
    "pass through de los filtros al subquery",
    "TOKEN: <valor desde Key Vault>",
    "secret = $AZURE_CLIENT_SECRET",
]

KNOWN_GAPS = [  # documentados; el detector heurístico no puede/debe cubrirlos
    "la clave de apps es Welcome1 en PROD",  # prosa
    "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",  # hex 40: puede ser un SHA de commit
    "pаssword = x",  # homoglifo cirílico
    "pass\u200bword = x",  # carácter de ancho cero
]


@pytest.mark.parametrize("text", MUST_REJECT)
def test_must_reject(text):
    with pytest.raises(ValueError):
        reject_secrets(text)


@pytest.mark.parametrize("text", MUST_ACCEPT)
def test_must_accept(text):
    reject_secrets(text)  # no debe lanzar


@pytest.mark.xfail(reason="hueco conocido e indetectable por heurística", strict=False)
@pytest.mark.parametrize("text", KNOWN_GAPS)
def test_known_gaps(text):
    with pytest.raises(ValueError):
        reject_secrets(text)
