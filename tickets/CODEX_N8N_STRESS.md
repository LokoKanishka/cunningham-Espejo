# TICKET: N8N Stress Harness + Matrix

Objetivo
- Ejecutar stress HTTP contra n8n local (127.0.0.1:5678) y producir artefactos reproducibles en `./_stress/`.

Tareas
1) Verificar que `scripts/n8n_stress.sh`:
   - espera readiness contra URL objetivo,
   - guarda: raw.csv + summary + docker stats before/after + metrics before/after + logs since start.
2) Verificar `scripts/n8n_stress_matrix.sh`:
   - corre N/P: (2000/50), (10000/100), (30000/200)
   - no rompe n8n (debe quedar up al final)

Criterio de aceptación (botón rojo)
- En los 3 escenarios: OK_RATE >= 0.995
- Artefactos en `./_stress/` con timestamp
- Output final de cada escenario imprime PASS/FAIL

Cómo ejecutar
- `URL=http://127.0.0.1:5678/healthz ./scripts/n8n_stress_matrix.sh`
