# S17: Trusted Publishing en PyPI

## Goal

Que 0.13.0 (y las siguientes) se publiquen desde GitHub Actions con OIDC, sin token
de API, y con attestations PEP 740. La página de 0.12.0 muestra "No provenance"
y "uploaded from a local environment" (`uv publish` desde local): es lo primero
que mira quien evalúa el paquete.

## Scope

- `.github/workflows/publish.yml` nuevo: se dispara con un push de tag `v*`.
- Job `build`: `uv build` (fresh checkout, no hay `dist/` ni `build/` huérfanos)
  y sube el artefacto. Sin permisos especiales.
- Job `publish`: baja el artefacto y publica con `pypa/gh-action-pypi-publish`
  (`id-token: write` solo en este job). Las attestations PEP 740 se generan por
  defecto en el flujo de Trusted Publishing; no se configuran aparte.
- Cero cambios en el código Python.

## Acceptance criteria

1. El YAML parsea y los dos jobs se ven en el run del primer tag.
2. PyPI muestra "Provenance" (uploaded via GitHub Actions OIDC) en 0.13.0.
3. No hay ningún secret de PyPI en el repo (`UV_PUBLISH_TOKEN` deja de usarse).

## Setup manual (una vez, antes del primer tag)

PyPI → `cairn-mem` → Settings → Publishing → "Add a new pending publisher":
owner `DavidPerezOrfila`, repo `cairn-mem`, workflow `publish.yml`,
environment vacío. Sin este alta, el primer run del tag falla con 403.

## Evidence

- Parseo del YAML validado localmente (`yaml.safe_load`): jobs `build` y
  `publish`, permisos `{'id-token': 'write'}` solo en `publish`.
- Criterio 2 y 3 se verifican al publicar la siguiente release.

## Out of scope

- TestPyPI, `workflow_dispatch`, guardas tag↔versión de `pyproject.toml`.
- El alta del pending publisher es un paso del dashboard de PyPI, no del repo.
