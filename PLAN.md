# PLAN — Proyecto “Moltbot Upstream Lab” (desde cero)

## 0) Qué es este repo (de verdad)
Repo nuevo y autónomo para:
1) Instalar y correr **Moltbot upstream** (tal cual lo publica el proyecto).
2) Usarlo con **modelos externos por API** (proveedores).
3) Habilitar **cambio de modelo** (perfiles) de forma reproducible.
4) Potenciarlo integrando **aportes de la comunidad** (GitHub) con proceso seguro y trazable.
5) Trabajar con **Codex en VS Code (Antigravity)** como ejecutor y este chat como arquitectura/supervisión.

## 1) Principios
- Open-source, reproducible, trazable.
- Seguridad primero: skills/extensiones = código ejecutable.
- Secretos fuera de git (API keys nunca se commitean).
- Trabajo por tickets encadenados (“tramos largos”) + verificación estándar.

## 2) Definition of Done
Logrado cuando:
1) Moltbot upstream instala y corre.
2) 1 proveedor externo responde a prompt mínimo.
3) Cambio de modelo (perfiles) probado.
4) Suite `scripts/verify_all.sh` valida end-to-end.
5) 1 integración comunitaria pinneada (commit/tag) + revisión + doc + smoke test.

## 3) Estructura target
/
├─ README.md
├─ PLAN.md
├─ .gitignore
├─ config/               # plantillas .env / perfiles
├─ runtime/              # instalación/runner upstream
├─ skills/               # integraciones (pin) + parches
├─ scripts/              # bootstrap + verify
└─ docs/                 # ADR + integraciones + seguridad

## 4) Roadmap (hitos)
- H0: bootstrap repo (docs + scripts + estructura).
- H1: instalar upstream (vanilla).
- H2: configurar proveedor externo.
- H3: perfiles y cambio de modelo.
- H4: 1ra skill comunitaria integrada (pin + doc + test).
- H5: hardening + reproducibilidad (bootstrap + verify_all).
