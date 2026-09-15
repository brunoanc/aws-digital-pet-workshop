# Adopta una mascota con IA en AWS

Un agente para consultar y cuidar una mascota digital con Python, Strands y servicios de AWS.

Guía para seguir con el facilitador. Solo se necesita un navegador y el acceso asignado al equipo.

## Tu equipo

El organizador te entregará estos datos por el canal del taller; no copies nombres de otro equipo.

| Dato | Uso |
|---|---|
| Portal SSO, usuario y contraseña asignados | Entrar a AWS con el acceso del equipo |
| Cuenta, permiso y región | Seleccionar el entorno del taller |
| ID del equipo | Identificar el item de tu mascota |
| Tabla DynamoDB | Ver y personalizar tu mascota |
| Lambda mascota | Leer reglas y escribir tu acción |
| Lambda agente | Escribir el modelo, prompt y herramientas |
| URL de la app y modelo autorizado | Conversar con tu agente |
| Hora de cierre | Guardar tu trabajo antes de perder acceso |

Usa la identidad asignada a tu equipo tanto en la consola como en la app. Mantén las credenciales dentro de tu equipo.

## Recorrido

Sigue las pausas de follow along de la presentación; no es necesario adelantar todo el código.

Tu trabajo queda en `agent_builder.py` de la Lambda agente y `custom_action.py` de la Lambda mascota; los handlers y la conexión a AWS ya están preparados. Guarda una copia antes de usar un checkpoint de rescate.

| Paso | Actividad | Evidencia |
|---|---|---|
| 1 | Acceso | Cuenta, equipo y región correctos |
| 2 | Conversación en Bedrock | Una respuesta no demuestra una consulta a la tabla |
| 3 | Mascota en DynamoDB | Nombre y especie aparecen en la ficha |
| 4 | Modelo, agente y prompt | El agente responde desde la app |
| 5 | Lambda Test y `inspect_pet` | Consulta real que coincide con DynamoDB |
| — | Break | Pausa antes de continuar |
| 6 | Cuidados | Acción real o rechazo explicado |
| 7 | Conectar la acción propia | Resultado visible en la actividad |
| 8 | CloudWatch | Log del rechazo de la acción pendiente |
| 9 | Implementar la acción | Efectos verificados en la mascota |
| 10 | Terminar y guardar | Código propio y estado conservados |

## 1. Entra y prepara tus pestañas

1. Abre el portal SSO e inicia sesión con tu usuario y contraseña.
2. Selecciona la cuenta y el permiso de tu equipo, no un permiso de administrador.
3. Comprueba la región asignada en la consola.
4. Abre esta guía y la app en pestañas distintas; inicia sesión en la app con la misma identidad.

**Comprueba**. Puedes entrar al entorno y la app reconoce tu equipo. Si falta una asignación o venció el acceso, consulta [ayuda](help.md); no crees otra cuenta ni cambies permisos.

## 2. Prueba el modelo en Bedrock

1. Abre Amazon Bedrock y el playground de chat que muestre el facilitador.
2. Selecciona el modelo y modo asignados para el taller.
3. Envía este mensaje. "Eres una mascota digital que aprende programación; preséntate en español y propón un reto sencillo".
4. Después pregunta. "¿Cuánta energía tiene mi mascota ahora? ¿Puedes consultar mi tabla DynamoDB?".

**Predice**. ¿Una respuesta convincente demuestra que leyó la tabla?

**Comprueba**. El playground no tiene conectada nuestra herramienta de consulta; no cuentes una afirmación del modelo como una lectura real. No necesitamos que el modelo invente datos para entender esa diferencia. Si el modelo no está disponible, avisa al facilitador y continúa cuando indique el punto de recuperación.

## 3. Adopta tu mascota en DynamoDB

1. Abre DynamoDB → **Tables** → tu tabla → **Explore table items**.
2. Abre el item cuyo `pet_id` sea exactamente el ID de tu equipo, en lugar de un registro interno `_op#...`.
3. Sin solicitudes activas en la app, edita únicamente `name` y `species`.
4. Elige **Dragón, Gato, Zorro o Ajolote** como especie y guarda los cambios.
5. Regresa a la app y pulsa **Actualizar ficha**.

**Comprueba**. Aparecen tu nombre y animal. No cambies claves, inventario, estadísticas ni versión; si abriste otro item, cancela. Ante una especie desconocida, revisa su escritura y consulta [ayuda](help.md).

**Predice**. ¿Cambiar el nombre en DynamoDB le permite al modelo conocerlo automáticamente?

## 4. Escribe el agente por etapas

Este bloque avanza por etapas, con un break después de la consulta y una visita a CloudWatch antes de implementar la acción propia.

Abre tu Lambda **agente** y, en **Configuration → Function URL**, copia la URL completa. Pégala en **Function URL de tu agente** en la app y pulsa **Conectar**. No pegues claves AWS ni la URL de otro equipo.

Sigue [Construye tu agente y dale una acción propia](../participant-guide/agent.md) con el facilitador.

1. En la sección 1, escribe los imports, `BedrockModel`, `Agent` y `return agent` en `agent_lambda/agent_builder.py`. Pulsa **Deploy** y pregunta "¿Cómo está mi mascota?". Guarda la respuesta. En la sección 2, añade tu system prompt, vuelve a desplegar y repite la pregunta para comparar.
2. En la sección 3, lee la consulta proporcionada, importa `inspect_pet` y agrégala a `tools`; compara la actividad con la ficha.
3. Después del break, en la sección 4, explora `rest` en `rules.py` de la función Lambda **mascota** y pruébalo una vez desde **Test**. Compara el resultado con DynamoDB. Después lee y registra `care_for_pet` en el agente, pulsa **Deploy** y pide que la mascota juegue una vez desde el chat. Comprueba la llamada con `play` y los cambios en la ficha.
4. En la sección 5 del código, importa y registra `custom_action`, añade las instrucciones al system prompt y pulsa **Deploy**. Pide la acción una vez y abre **Actividad de las herramientas**. Copia el `request_id` del resultado con `BACKEND_ERROR`.
5. Sigue la sección 5 de esta guía para localizar el error en CloudWatch antes de cambiar el código.
6. Vuelve a `custom_action.py` de la función **mascota** y escribe `perform(pet)` con condición, efectos y mensaje; pulsa **Deploy** y verifica una ejecución desde la app.

Antes del descanso debes tener una consulta real; al terminar este bloque debes tener una acción propia. Si falta alguna, pide ayuda para recuperar ese paso y conserva lo que ya escribiste.

Cada sección incluye un checkpoint de rescate. Conserva una copia de tu código antes de reemplazarlo; usar un checkpoint permite recuperar el ejercicio, pero después personalízalo y explica qué hace.

### Una prueba directa de Lambda

En el bloque de consulta, antes de registrar `inspect_pet`, abre **Test** en la función Lambda **mascota**. Crea un evento y sustituye `team-01` por el ID asignado.

```json
{"pet_id": "team-01", "action": "inspect", "parameters": {}}
```

Comprueba `success: true` y compara nombre y energía con DynamoDB. Después registra la herramienta y compara con la consulta desde el chat. En Test eliges la acción directamente; en el chat, el modelo solicita la tool y Strands la ejecuta. No pegues este evento en la función del agente, que espera un `message` de texto.

## 5. Localiza el error en CloudWatch

1. Abre CloudWatch → **Log groups** → el grupo de la Lambda **mascota** de tu equipo.
2. Busca en los streams recientes el `request_id` que copiaste del resultado de la tool. Usa el ID entre comillas como filtro y actualiza si los eventos todavía no llegan.
3. Expande el evento `PET_BACKEND_ERROR` del equipo. `exception_type` indica el tipo de error y `frames` muestra los archivos, las funciones y las líneas por donde pasó la ejecución. Revisa el último elemento.
4. Abre el archivo y la línea indicados en la función Lambda **mascota**. En el starter, `perform` lanza `NotImplementedError` porque falta escribir sus efectos. Reemplaza ese `raise` por tu implementación y pulsa **Deploy**.
5. Consulta el estado, solicita la acción una vez y compara los cambios. Comprueba el resultado en la actividad.

**Comprueba**. El ID del log coincide con el `request_id` del resultado de la tool, dentro de la actividad. Es distinto del `operation_id`. El log permite localizar el error que la respuesta general omitía. Si tu acción ya estaba implementada, pide al facilitador una evidencia de referencia, identificada como ejemplo.

El error del starter ocurre antes de guardar cambios. Otros errores pueden dejar un resultado incierto, por eso hay que revisar el estado antes de reintentar. Una regla como `NEEDS_REST` devuelve un rechazo esperado y genera `PET_ACTION_REJECTED`, en lugar de una excepción. Basta leer la condición para explicar ese caso.

## 6. Guarda lo que construiste

1. Copia tu `agent_builder.py` y el `custom_action.py` que escribiste a archivos locales.
2. Conserva una copia del JSON de tu mascota si quieres guardar su estado; no copies registros internos ni credenciales.
3. Obtén del facilitador el enlace de la versión del repo utilizada.
4. Comprueba que los archivos se abren antes de cerrar sesión.

Guardar los archivos no mantiene el servicio funcionando después del taller. Para continuar se necesita un entorno AWS propio, que puede generar cargos. El guardado del código es manual.

**Para cerrar**. Explica qué parte escribiste tú, cómo el agente elige una herramienta y dónde se guardan los cambios reales.
