# Autonomy + Vision Stack (10 módulos)

Objetivo: ampliar autonomía operativa y visión del agente sin API keys pagas.

## 1) Memoria semántica local
Script: `scripts/memory_semantic.sh`
- `status`: estado del índice
- `index`: reindexado
- `search <query>`: búsqueda

## 2) Visión web por tool (web_fetch/web_search)
Script: `scripts/browser_vision.sh`
- `probe`: valida disponibilidad real del tool
- `search <query>`: búsqueda con resumen por agente

## 3) Watcher de workspace
Script: `scripts/watch_workspace.sh`
- `watch_workspace.sh <ruta> watch`
- `watch_workspace.sh <ruta> check`

## 4) Planner + Executor en dos etapas
Script: `scripts/plan_execute.sh`
- `plan_execute.sh "tarea"`
- `plan_execute.sh check`

## 5) Aprobaciones Lobster
Script: `scripts/lobster_approval.sh`
- `lobster_approval.sh <resume-token> yes|no`
- `lobster_approval.sh check`

## 6) RPA de navegador
Script: `scripts/rpa_web_task.sh`
- `rpa_web_task.sh check`
- `rpa_web_task.sh run <url>`

## 7) Observabilidad operativa
Script: `scripts/ops_observe.sh`
- genera `DOCS/RUNS/ops_<timestamp>.log`

## 8) Goal queue persistente
Script: `scripts/goals_queue.sh`
- `add`, `list`, `next`, `done`

## 9) Git autopilot seguro
Script: `scripts/git_autopilot.sh`
- `check`
- `git_autopilot.sh <branch> <commit-msg> [paths...]`

## 10) Ingesta de conocimiento local
Script: `scripts/knowledge_ingest.sh`
- consolida docs en `~/.openclaw/workspace/KNOWLEDGE_LOCAL.md`
- dispara `openclaw memory index`

## Verificación de stack
Script: `scripts/verify_stack10.sh`
- valida ejecutables
- corre checks/dry-run por módulo
- imprime `STACK10_OK`
