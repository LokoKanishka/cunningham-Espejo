# Autonomy + Vision Stack (Next 10)

Extensión del stack original con 10 módulos adicionales, priorizando autonomía controlada y visión local/web.

## Módulos
1. Auto-healing gateway: `scripts/gateway_autoheal.sh`
2. Perfilador de tareas: `scripts/task_profile.sh`
3. Router multi-modelo + fallback: `scripts/model_router.sh`
4. Visión local OCR/PDF: `scripts/local_vision.sh`
5. Diff intelligence: `scripts/diff_intel.sh`
6. Autotest runner/scaffold: `scripts/autotest_gen.sh`
7. Runbooks ejecutables: `scripts/runbook.sh`
8. Policy engine por riesgo: `scripts/policy_engine.sh`
9. ADR bot (decisiones): `scripts/adr_bot.sh`
10. Dashboard local de ops: `scripts/ops_dashboard.sh`

## Verificación
- `./scripts/verify_next10.sh` -> `NEXT10_OK`
- Baseline estable: `./scripts/verify_all.sh` -> `ALL_OK`

## Nota de red
El módulo web puede operar en modo "tool disponible pero red DNS caída" sin marcar error de permisos.

## Extras integrados
11. Worker de objetivos: `scripts/goals_worker.sh`
12. Alertas operativas locales: `scripts/ops_alerts.sh`
13. Investigación web con reporte: `scripts/web_research.sh`

Checks:
- `./scripts/goals_worker.sh check`
- `./scripts/ops_alerts.sh check`
- `./scripts/web_research.sh check`
