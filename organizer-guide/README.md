# Guía del organizador

Ruta para preparar, impartir y cerrar el workshop. La [guía de participantes](../participant-guide/README.md) describe la práctica; [docs](../docs/README.md) contiene los pasos de configuración y operación.

## 1. Preparar el entorno

Necesitas una Organization y cuentas miembro existentes, acceso SSO de administración, Terraform, GNU Make, Python 3.13, uv y Node.js para las slides.

```bash
uv sync --locked
make test
npm --prefix slides ci
npm --prefix slides run build
```

Usa una cuenta miembro para el evento, otra para ensayo y management únicamente para control y state. Elige una región común para Bedrock, mascotas, agentes, Cognito y servidor; confirma disponibilidad del modelo y cuotas antes del deploy. El certificado de CloudFront siempre se solicita en `us-east-1`. Si cambias el modelo o sus límites, actualiza también los ejemplos de las guías, los checkpoints y las slides.

Completa `environment.json` y `teams.json` en `.local/` siguiendo la [configuración común](../config/README.md). Genera los archivos para Terraform y las herramientas. Los backends y los secretos se preparan por separado; revisa cada plan antes de aplicar.

## 2. Infraestructura y orden de deploy

| Stack | Función | Referencia |
|---|---|---|
| `infra/bootstrap` | Bucket de state | [Bootstrap](../docs/infrastructure.md#bootstrap) |
| `infra/control` | Presupuesto, controles y acceso | [Control](../docs/infrastructure.md#control), [participantes](../docs/infrastructure.md#access) |
| `infra/pets` | Mascota, tabla y logs por equipo | [Mascotas](../docs/deployment.md#pets) |
| `infra/agent` | Agente editable por state | [Agente](../docs/deployment.md#agent) |
| `infra/ui-auth` | Cognito y federación | [Login](../docs/infrastructure.md#login) |
| `infra/ui-host` | Servidor y permisos de la web | [Hosting](../docs/infrastructure.md#hosting) |
| `infra/slides-hosting` | Presentación independiente | [Slides](../infra/slides-hosting/README.md) |

Cada stack necesita una key de state exclusiva. Cada agente necesita también su propia configuración y `TF_DATA_DIR`. Conserva esas asociaciones en un inventario privado. No cambies una key de staging por una de evento para reutilizar un directorio ya inicializado.

1. Prepara state, presupuesto y controles.
2. Crea mascotas e [inicializa los datos](../docs/deployment.md#seed), sin sobrescribir items existentes.
3. Construye la capa y crea los agentes con los starters, no con las soluciones.
4. Completa los permisos de equipos para sus funciones y logs.
5. Crea autenticación y host; configura DNS y la aplicación SAML de Identity Center.
6. Haz el deploy del proxy, el login y la app siguiendo el [flujo de deploy](../docs/deployment.md#release).
7. Registra los destinos exactos de cada equipo y habilita el acceso solo dentro de la ventana prevista.

Revisa cuenta, región, recursos y destrucciones en cada plan. Aplica únicamente el plan revisado. Actualiza el software del servidor y las slides mediante sus comandos de deploy.

## 3. Acceso de equipos

Asigna las identidades del taller a sus equipos. El lab permite una o varias identidades por equipo, sin crear una cuenta AWS para cada uno.

Prepara y prueba antes del evento.

- Portal SSO, usuario y contraseña del equipo, compartidos por un canal privado.
- Cuenta, permission set y región asignados.
- ID del equipo, tabla y nombres de las dos funciones Lambda.
- URL de la web y modelo autorizado.
- Hora de cierre y forma de pedir ayuda.

Empieza con un usuario de prueba. [Crea el usuario en Identity Center](../docs/infrastructure.md#access-membresías-de-identidades-existentes), envía la invitación para crear la contraseña y verifica la recuperación de acceso. Si usas un correo con forwarding por equipo, comprueba que los mensajes llegan al destinatario previsto.

Durante la prueba piloto, usa `identity_center.assignment_teams = ["team-00"]` y `identity_center.assignments_enabled = true` en `environment.json`. Revisa que el plan habilite únicamente ese equipo. Al preparar los participantes, amplía la lista después de validar sus identidades.

El acceso tiene tres partes independientes.

- **Login de la web**. Crea la [aplicación SAML](../docs/infrastructure.md#login-etapa-2-aplicación-manual-en-identity-center) y [asigna el usuario](../docs/infrastructure.md#login-asignar-usuarios-a-la-aplicación) desde **Assign users and groups**. Esto permite autenticarse mediante Cognito.
- **Consola de AWS**. Registra el `UserId` en `identity_center_user_ids` del equipo en `teams.json`. Terraform administra la membresía del grupo y la asignación del permission set a la cuenta AWS.
- **Equipo en la app**. Después del primer login, verifica el perfil de Cognito y registra su `sub` en `cognito_subjects`. Aplica la [política de acceso](../docs/infrastructure.md#login-asignar-equipos-después-de-verificar-la-federación) con las identidades aprobadas y la ventana de prueba.

Con la política deshabilitada, el login debe regresar al aviso de acceso no habilitado. Después de asociar el perfil y habilitar la ventana, el login aislado debe confirmar el equipo correcto. Completa esta prueba antes del release de la app con la mascota y antes de abrir el acceso a los participantes.

Para un taller de tres horas, configura `access.max_session_seconds = 14400` y una ventana que cubra también el acceso previo. Aplica tanto Terraform de `ui-auth` como la política del servidor, según la [configuración de sesiones](../config/README.md#equipos-y-acceso). Prueba con un login nuevo; los tokens anteriores conservan su vencimiento. La sesión de la consola AWS se configura por separado.

## 4. Prueba end-to-end

Usa un equipo piloto separado, con los mismos permisos que los participantes. Una prueba con la sesión administradora no valida el acceso del alumno.

- [ ] Login en consola y app; cuenta, región y equipo correctos.
- [ ] Bedrock permite conversar con el modelo autorizado.
- [ ] Editar únicamente `name` y `species` refleja el cambio en la ficha.
- [ ] Copiar y conectar la Function URL asignada funciona; otra URL se rechaza.
- [ ] Escribir constructor y prompt produce una respuesta.
- [ ] Lambda Test ejecuta `inspect` y sus datos coinciden con DynamoDB.
- [ ] Registrar `inspect_pet` permite consultar desde el chat.
- [ ] Probar `rest` desde Test en la función mascota produce un cambio o un rechazo que coincide con `rules.py`.
- [ ] Registrar `care_for_pet` permite pedir `play` desde el chat después del descanso y comprobar sus cambios.
- [ ] Registrar `custom_action` y actualizar el prompt muestra `BACKEND_ERROR` con un `request_id` en la actividad.
- [ ] El mismo ID permite encontrar `PET_BACKEND_ERROR` en CloudWatch, con `NotImplementedError` y la ubicación de `perform` en `custom_action.py`.
- [ ] El error del starter conserva el estado y permite completar la acción antes de probarla nuevamente.
- [ ] Implementar `perform(pet)` permite verificar sus efectos.
- [ ] Un timeout no provoca reintentos automáticos de cuidados.
- [ ] Guardar código y recuperar desde checkpoints funciona.

Después prueba la cantidad prevista de sesiones web simultáneas, aislamiento entre equipos, límites de concurrencia y bloqueo de acceso. La [prueba de capacidad del backend](../docs/testing.md#capacity) no sustituye esta pasada de navegador. Usa recursos temporales y elimina solo los de esa prueba con un plan revisado.

## 5. Durante el taller

Sigue las slides y la guía de participantes en el mismo orden. Usa Lambda Test para probar las acciones antes de conectarlas al agente. En el ejercicio de CloudWatch, busca el ID de la actividad para localizar el tipo de excepción, el archivo y la línea del error.

Ajusta el ritmo y el break al avance de los equipos. Usa los checkpoints para recuperar el flujo y reserva espacio para terminar y guardar.

Antes de reemplazar código con una solución, conserva el trabajo del equipo. Si no aparece el rechazo esperado porque la acción ya está implementada, usa evidencia de referencia; no borres código para fabricar el error.

## 6. Recuperación y cierre

Ante un problema, registra equipo, hora y error sin tokens ni contraseñas. Consulta [diagnóstico](../docs/testing.md#diagnostics) y [ayuda](../participant-guide/help.md). No repitas operaciones con resultado desconocido.

Para un release fallido, consulta el status, verifica el fingerprint y usa el backup según el [flujo de deploy](../docs/deployment.md#release). Prueba la recuperación antes del evento.

Al cerrar.

1. Guarda código, datos y evidencia necesarios fuera del repo público.
2. Cierra la ventana de acceso y verifica el bloqueo.
3. Retira staging solo después de validar el entorno definitivo.
4. Revisa los planes de destrucción de servidor/autenticación, agentes, mascotas y permisos, respetando sus dependencias.
5. Conserva el bucket de state y sus versiones; las slides tienen su propio ciclo de vida y no se desmontan con el lab.
6. Comprueba recursos restantes y facturación; confirma la retirada de los recursos directamente en AWS.

## 7. Distribuir una adaptación

Ejecuta los tests, revisa enlaces y ejemplos, y excluye credenciales, datos de participantes, estados y backups. Revisa también el historial Git si existe. Conserva `LICENSE` y los avisos de terceros; una versión modificada accesible por red debe ofrecer el código fuente correspondiente según AGPLv3.

Para hacer el deploy de las slides, sigue su [guía de edición y deploy](../slides/README.md). Las notas del presentador también son públicas.

Antes de distribuir las slides, actualiza el título, la fecha, el presentador, los enlaces SSO y de la app, y los datos del grupo según la [guía de edición](../slides/README.md#editar).
