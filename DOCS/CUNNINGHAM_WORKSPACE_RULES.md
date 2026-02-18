# Reglas de Workspace (Permanentes)

Estas reglas aplican siempre para Cunningham en Ubuntu:

1. No mover ventanas existentes entre workspaces.
2. No reutilizar ni "traer" ventanas que ya estaban abiertas en otro workspace.
3. Para pruebas, abrir siempre ventana nueva en el workspace activo.
4. Si no se puede garantizar aislamiento por workspace, detenerse y pedir confirmación.
5. Se puede usar el perfil Chrome solicitado (por ejemplo `diego`) pero solo abriendo ventana nueva en el workspace activo.
6. Prohibido usar comandos/acciones que cambien de workspace una ventana (por ejemplo `wmctrl -t` o equivalente).
7. Si una ventana se abrió por error en otro workspace, no moverla: dejarla donde está y continuar solo en el workspace actual.

## Modo aislado por display (recomendado)

Para evitar que pruebas UI invadan otros workspaces, usar display aislado:

1. Modo "no me jodas" (headless): `scripts/api_youtube_isolated.sh headless stress10`
2. Modo "quiero mirar" (visible encapsulado, backend inestable): `ISO_ALLOW_UNSTABLE_VISIBLE=1 scripts/api_youtube_isolated.sh visible seq`
3. Control manual:
`ISO_ALLOW_UNSTABLE_VISIBLE=1 scripts/display_isolation.sh up visible`
`scripts/display_isolation.sh exec -- <comando>`
`scripts/display_isolation.sh down`

Este enfoque no mueve ventanas entre workspaces: toda la UI de prueba vive dentro del display aislado.
Default recomendado en host: `DIRECT_CHAT_FOLLOW_ACTIVE_WORKSPACE=0` para mantener workspace fijo del agente.
Default recomendado adicional: `DIRECT_CHAT_TEMP_SWITCH_WORKSPACE=0` para no saltar entre escritorios.

## Modo "como humano en el chat" (permanente)

Cuando el usuario pida operar "como humano en el chat":

1. Usar `Molbot Direct Chat` visible como canal obligatorio.
2. Si ya está abierto, usar esa misma ventana/pestaña.
3. Escribir y enviar en el chat como lo haría el usuario.
4. Evitar atajos internos/API para esa prueba: priorizar interacción de interfaz real.
5. Objetivo: validar comportamiento real de UI (incluyendo fallos de interfaz).

## Alias permanentes

1. `cunn` = `Cunningham` (la IA del proyecto).
2. `dc` = `Molbot Direct Chat`.
