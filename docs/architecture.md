# Arquitectura

La app conecta a cada equipo con su agente y su mascota. El agente usa Strands y Bedrock para elegir tools; la función Lambda de la mascota valida las acciones y guarda los cambios en DynamoDB.

## Contenido

- [Function URL](#url)
- [Chat por equipo](#chat)
- [Ficha, especies y animaciones](#card)

<a id="url"></a>

## Function URL

La app llama al agente mediante una Function URL con autenticación `AWS_IAM`. El servidor usa credenciales temporales del rol del equipo para firmar las solicitudes. El participante solo necesita iniciar sesión y conectar la URL asignada.

### Configuración

1. Activa `web.chat_enabled` en `environment.json` y genera los archivos según la [configuración común](../config/README.md).
2. Haz el deploy de cada agente con su backend y sus variables. La salida `inventory.function_url` contiene su dirección.
3. Registra esa dirección en `function_url` del equipo correspondiente en `teams.json`.
4. Genera otra carpeta de configuración y comprueba los destinos de `shared-card.json`.
5. Aplica los permisos del hosting y haz el [deploy de la app](deployment.md#card-actualización-y-recuperación-del-servicio).

El rol de cada equipo necesita leer la configuración del agente e invocar su Function URL. Conserva los permisos generados por Terraform y la autenticación `AWS_IAM`. Consulta los [requisitos de autorización de Function URLs](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) si adaptas los roles.

### Conexión desde la app

1. Abre la función Lambda **agente** y selecciona **Configuration → Function URL**.
2. Copia la dirección HTTPS completa.
3. Pégala en **Function URL de tu agente** y pulsa **Conectar**.
4. Espera el mensaje **Agente conectado** antes de usar el chat.

La app comprueba que la URL pertenece al agente del equipo y conserva la dirección validada en ese navegador. Al abrir otra sesión, vuelve a verificarla. En otro navegador, o después de borrar sus datos, es necesario pegarla nuevamente.

Abrir la URL directamente en el navegador no muestra el chat. Las llamadas necesitan autenticación IAM y se realizan desde el servidor de la app.

### Comprobaciones

Con una identidad participante, conecta la URL asignada y envía una consulta del estado. Comprueba que la actividad y la ficha correspondan al mismo equipo. Prueba también una URL ajena y un usuario sin asignación; ambos deben ser rechazados.

Ante un timeout o un resultado incierto, consulta el estado antes de repetir un cuidado. Para cerrar el acceso, usa la [política de la app y los controles de AWS](infrastructure.md#access-interruptor-de-emergencia); eliminar una Function URL por sí sola no revoca otros permisos de invocación.

<a id="chat"></a>

## Chat por equipo

La app muestra la conexión, la ficha y el chat. La actividad permite consultar las tools ejecutadas y sus resultados.

### Configuración

Activa `web.cards_enabled` y `web.chat_enabled` en el entorno. El archivo generado `shared-card.json` contiene los destinos, el modelo y los límites de cada equipo. Comprueba estos valores contra las salidas de Terraform antes del deploy.

El servidor obtiene el equipo desde la identidad y la política de acceso. Los permisos generados permiten llamar al agente asignado y leer la mascota correspondiente. Usa datos ficticios; el servidor administra los accesos de todos los equipos y necesita protección administrativa.

### Comportamiento y límites

- Cada mensaje es independiente. El historial permanece visible en la app, pero no se envía al agente.
- Solo se procesa una solicitud por equipo a la vez.
- `max_requests` limita la cantidad de solicitudes y `min_interval_seconds` define la espera entre ellas. Revisa ambos valores en la sección `agent` de cada equipo en `shared-card.json` antes del deploy.
- La cuota se comparte entre las sesiones del equipo y se conserva tras reiniciar el servicio. Cambiar la ventana de acceso conserva el consumo acumulado.
- Una solicitud enviada cuenta aunque su resultado sea incierto. Consulta el estado antes de repetirla.

Los controles de concurrencia y cuota están diseñados para una sola instancia del servidor. Un deploy con varias instancias requiere adaptar estos controles para que compartan el consumo de cada equipo.

Prueba dos sesiones del mismo equipo y otra de un equipo distinto. Comprueba el aviso de solicitud en curso y que el otro equipo pueda seguir trabajando. Revisa también el login, el logout y la expiración de sesiones con la [checklist end-to-end](../organizer-guide/README.md#4-prueba-end-to-end).

<a id="card"></a>

## Ficha, especies y animaciones

La ficha lee el estado de DynamoDB con permisos de solo lectura. La respuesta del modelo no es su fuente de datos.

### Lectura y actualización

La app carga la ficha al entrar y conserva el último estado leído durante la sesión. Pulsa **Actualizar ficha** después de editar la mascota en DynamoDB. El chat también solicita una actualización después de ejecutar tools.

Las lecturas tienen un intervalo mínimo de dos segundos por equipo, compartido entre sus sesiones. Si una actualización falla o alcanza el límite, la app conserva la ficha anterior con un aviso de que debe actualizarse. Espera y pulsa **Actualizar ficha**.

El acceso se comprueba antes de mostrar la ficha. La revocación impide nuevas consultas, aunque los datos ya mostrados pueden permanecer en una pestaña abierta.

### Especies y animaciones

`species` admite **Dragón, Gato, Zorro y Ajolote**. Todas las especies comparten reglas y estadísticas. Un valor desconocido muestra una ilustración genérica; corrige el campo en DynamoDB para cambiarla.

Las animaciones representan cuidados confirmados en los datos guardados, no afirmaciones del modelo. La app respeta la preferencia de movimiento reducido del navegador.

### Configuración y retirada

Activa `web.cards_enabled` para generar los permisos de lectura del hosting. Revisa las tablas y los roles de `shared-card.json` antes del [deploy de la app](deployment.md#card-actualización-y-recuperación-del-servicio). Si `web.chat_enabled` está deshabilitado, la app muestra solo la ficha.

Para cerrar el taller, deshabilita el acceso y sigue la [retirada del servicio](deployment.md#card-retirada). Los stacks de agentes y mascotas tienen su propio ciclo de vida; exporta el trabajo antes de destruirlos.
