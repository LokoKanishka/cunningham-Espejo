# Reglas de Workspace (Permanentes)

Estas reglas aplican siempre para Cunningham en Ubuntu:

1. No mover ventanas existentes entre workspaces.
2. No reutilizar ni "traer" ventanas que ya estaban abiertas en otro workspace.
3. Para pruebas, abrir siempre ventana nueva en el workspace activo.
4. Si no se puede garantizar aislamiento por workspace, detenerse y pedir confirmación.
5. Se puede usar el perfil Chrome solicitado (por ejemplo `diego`) pero solo abriendo ventana nueva en el workspace activo.

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
