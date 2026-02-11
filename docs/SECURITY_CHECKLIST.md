# Security checklist (skills/extensiones de terceros)

Antes de integrar:
- Licencia clara (ideal: MIT/Apache-2.0/BSD)
- Actividad (commits recientes, issues respondidos)
- Evitar installers opacos (curl|bash sin auditar, binarios sin source)
- Revisar:
  - shell-outs (`os.system`, `subprocess`, `exec`)
  - lectura/escritura de archivos
  - llamadas de red y endpoints
  - permisos y rutas peligrosas
- Pin por tag o commit hash
- Registrar en `docs/INTEGRATIONS.md`
