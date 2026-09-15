# Deploy y recuperación

Creación de mascotas y agentes, inicialización de datos y deploy del software. Revisa cada plan antes de aplicar cambios.

## Contenido

- [Recursos de mascotas](#pets)
- [Inicialización y prueba de mascotas](#seed)
- [Agente editable](#agent)
- [Deploy y recuperación de la app](#release)
- [Actualizar y recuperar el servicio](#card-actualización-y-recuperación-del-servicio)

<a id="pets"></a>

## Recursos de mascotas

`infra/pets` crea una tabla DynamoDB bajo demanda, un grupo de logs, un rol de ejecución, su política y una función Lambda por equipo. Las tablas nacen vacías.

<a id="pets-configuración-y-plan"></a>

### Configuración y plan

Completa antes [bootstrap](infrastructure.md#bootstrap) y [permisos](infrastructure.md#access). Genera `pets.tfvars.json` con la [configuración común](../config/README.md). Copia la plantilla de backend remoto a `.local/pets.tfbackend` y usa una key de estado exclusiva.

El backend usa el perfil **administrador** y el provider usa el de la **cuenta del lab**. Deben ser cuentas distintas. Comprueba que los IDs de equipo y los nombres de tabla y función coincidan con `participant_access`. Revisa juntos los permisos y los recursos antes de cada deploy.

Configura la región, los perfiles, los equipos, las etiquetas, la memoria, el timeout y la retención de los logs. El runtime admitido es Python 3.13; prueba cualquier otra versión antes de cambiar esa validación. Las funciones se crean sin concurrencia reservada para evitar conflictos con las cuotas de cuentas nuevas. Revisa las cuotas y el presupuesto antes de abrir el acceso.

Ejecuta estos comandos desde la raíz del repo.

```bash
python3 -m unittest discover -s tests -v
terraform -chdir=infra/pets init -backend-config=../../.local/pets.tfbackend
terraform -chdir=infra/pets validate
terraform -chdir=infra/pets test
terraform -chdir=infra/pets plan -var-file=../../.local/event-config/pets.tfvars.json -out=../../.local/pets.tfplan
terraform -chdir=infra/pets show ../../.local/pets.tfplan
```

Revisa las adiciones previstas para los equipos configurados, la cuenta y los ARNs de los recursos. Comprueba que cada rol permita leer y escribir únicamente su tabla y sus logs. El plan debe conservar los recursos de administración.

Aplica el plan después de revisarlo.

```bash
terraform -chdir=infra/pets apply ../../.local/pets.tfplan
terraform -chdir=infra/pets plan -var-file=../../.local/event-config/pets.tfvars.json
terraform -chdir=infra/pets output -json inventory
```

El segundo plan debe quedar sin cambios. Antes de usar la mascota, sigue [la inicialización y prueba real](deployment.md#seed), y después comprueba el acceso de los alumnos. No se administran items con Terraform; los siguientes applies no deben restablecer el progreso de estudiantes.

<a id="pets-código-editable-y-contrato"></a>

### Código y eventos de prueba

`rules.py` contiene las reglas de consulta y cuidado; la acción propia se escribe en `custom_action.py`. El handler valida las acciones y guarda los cambios en DynamoDB. Durante el ensayo, comprueba que la función pueda leer y actualizar su mascota.

El archivo `fixtures/starter.json` propone los datos iniciales, sin `pet_id`; al inicializar se asignará el ID de equipo. No contiene secretos ni datos reales. La tabla usa clave de partición string `pet_id`.

Evento de Test para consultar una mascota ya inicializada.

```json
{"pet_id": "team-01", "action": "inspect", "parameters": {}}
```

Evento para alimentarla.

```json
{"pet_id": "team-01", "action": "feed", "parameters": {"food": "healthy_meal"}, "operation_id": "prueba-comida-01"}
```

Repetir el mismo ID y acción devuelve el resultado guardado, sin consumir otra comida. Usa un ID nuevo cuando quieras ejecutar otra acción. Si omites el ID, cada clic cuenta como una acción nueva. Las tools generan un ID por operación y evitan repetir solicitudes con resultado incierto.

Los registros `_op#ID` conservan los resultados de las operaciones y evitan repetir una misma acción. Consérvalos durante el taller. Para consultar el estado actual, usa `inspect`.

Las reglas mantienen salud, saciedad, energía y felicidad entre 0 y 100. También validan el inventario y las acciones. Las ediciones en consola omiten estas reglas, así que hazlas con la app inactiva. Modificar o borrar registros internos puede permitir que una acción se ejecute otra vez. El rol de la función se limita a su tabla y sus logs, sin acceso a Bedrock, secretos ni tablas ajenas.

Antes de actualizar el ZIP con Terraform, exporta el trabajo de los participantes. El deploy puede reemplazar sus cambios hechos en consola.

<a id="pets-verificación-del-entorno"></a>

### Verificación del entorno

Las pruebas locales no sustituyen AWS. En cada entorno nuevo, comprueba la persistencia, la concurrencia, los permisos, la edición en consola y el aislamiento entre equipos. Registra la evidencia del piloto en la checklist del organizador antes de abrir el acceso.

<a id="pets-limpieza"></a>

### Limpieza

Exporta el trabajo y [bloquea el acceso](infrastructure.md#access). Conserva la SCP durante la expiración de las sesiones. Después genera y revisa el plan de eliminación.

```bash
terraform -chdir=infra/pets plan -destroy -var-file=../../.local/event-config/pets.tfvars.json -out=../../.local/pets-destroy.tfplan
terraform -chdir=infra/pets show ../../.local/pets-destroy.tfplan
```

Solo después de verificar cuenta y los recursos concretos, aplica ese plan. Se borran tablas y datos (incluidos `_op#ID`), funciones, roles/políticas y logs. No se habilitan backups/PITR para estas mascotas ficticias; sin exportación no hay recuperación garantizada. No borres el bucket de estado ni ejecutes destroy en bootstrap/control como parte de esta operación. Verifica los recursos restantes y la facturación después.

<a id="seed"></a>

## Inicialización y prueba de mascotas

Requiere [los recursos del lab](deployment.md#pets), Python 3 y AWS CLI v2 con una sesión SSO administrativa. Estas operaciones escriben datos e invocan Lambda, por lo que generan consumo AWS.

<a id="seed-configuración"></a>

### Configuración

Usa `.local/event-config/operations.json`, generado desde el entorno y los equipos. La tabla y la función comparten el nombre configurado. El fixture tiene una ruta absoluta a `fixtures/starter.json`. El script verifica STS, las tablas y las variables de las funciones antes de escribir.

El script asigna `pet_id` por equipo al crear los datos de `fixtures/starter.json`. La inicialización crea las mascotas; el prompt y las tools se definen en el código del agente.

<a id="seed-inicialización-sin-sobrescribir"></a>

### Inicialización sin sobrescribir

Desde la raíz del repo, ejecuta primero el preview. Solo consulta datos.

```bash
python3 scripts/seed.py --config .local/event-config/operations.json
```

Revisa las tablas y las claves antes de aplicar.

```bash
python3 scripts/seed.py --config .local/event-config/operations.json --apply
```

Si una mascota ya existe, el script conserva su contenido aunque sea distinto de la plantilla. Si la ejecución falla a mitad, corrige el problema y repite el comando; los registros ya creados se conservan. En el preview verás `pendiente` o `existe`; al aplicar, `creado` o `preservado`.

No se administran estos registros con Terraform. Modificar el fixture no actualiza mascotas existentes; cualquier restablecimiento posterior requerirá una operación separada y explícita.

<a id="seed-prueba-con-una-alimentación-real"></a>

### Prueba con una alimentación real

El equipo elegido debe tener comida saludable y saciedad inferior a 90. Usa un ID de prueba nuevo, manteniendo a otros operadores y la app inactivos.

```bash
python3 scripts/verify_pet.py --config .local/event-config/operations.json --team team-01 --operation-id ensayo-comida-001 --allow-mutation
```

Comprueba los siguientes resultados.

1. La lectura Lambda coincide con una lectura consistente de DynamoDB.
2. Dos solicitudes al mismo tiempo con el mismo ID, seguidas de un reintento, producen una sola alimentación.
3. El inventario disminuye en una comida; saciedad/salud/felicidad y versión coinciden con esa única acción.
4. Existe el registro persistente `_op#ID` con el resultado.
5. Reutilizar el ID para descansar es rechazado.
6. Si hay otro equipo configurado, la función rechaza inspeccionarlo y su mascota permanece sin cambios.

El reporte muestra el estado anterior y posterior. La comida consumida y el registro de operación quedan guardados. Si el ID ya existe, la prueba se detiene. Ante un fallo, consulta el estado y el registro antes de elegir otro ID; la acción pudo completarse.

La prueba envía solicitudes al mismo tiempo, aunque el servidor puede procesarlas en momentos distintos. Comprueba los reintentos, no la capacidad de carga. Como usa credenciales administrativas, `WRONG_TEAM` solo valida el handler. Comprueba también los permisos con dos usuarios de prueba y verifica el bloqueo de sus sesiones.

Ejecuta otra vez `seed.py --apply` para comprobar que conserva el progreso. Cada mascota existente debe aparecer como `preservado`.

<a id="seed-ver-desde-la-consola"></a>

### Ver desde la consola

- **DynamoDB → Tables → tabla del equipo → Explore table items**; mascota y registros `_op#ID` después de acciones. No modificar registros internos.
- **Lambda → Functions → función del equipo → Test**. Usa el evento `inspect` del [ejemplo](deployment.md#pets-código-editable-y-contrato).
- **CloudWatch → Log groups → /aws/lambda/función**. Busca `PET_ACTION_ACCEPTED`, `PET_ACTION_REJECTED` o `PET_BACKEND_ERROR`. Los errores incluyen el tipo de excepción y su ubicación en el código. El `request_id` coincide con el que devuelve la tool en un `BACKEND_ERROR`.

Los logs registran metadatos de ejecución y códigos de resultado. No compartas los archivos privados de configuración o los estados Terraform en el material público.

<a id="agent"></a>

## Agente editable

El agente se ejecuta en Lambda y la web compartida se conecta mediante una Function URL con autenticación IAM. El alumnado escribe `agent_lambda/agent_builder.py`; los helpers y las dependencias están preparados.

<a id="agent-preparar-el-paquete"></a>

### Preparar el paquete

```bash
uv run --locked python scripts/build_agent_layer.py \
  --requirements agent_lambda/layer/requirements.lock \
  --output .local/agent-layer
```

El directorio de salida debe ser nuevo. El script genera `agent-layer.zip` y un reporte. La capa usa Python 3.13 y Linux x86_64. Configura su ruta en `layer_zip_path` de `environment.json` antes de generar las variables del agente.

<a id="agent-un-state-por-agente"></a>

### Un state por agente

`infra/agent` crea una función, un rol, un grupo de logs, una capa y una Function URL opcional. Usa los archivos generados `team-01-agent.tfvars.json` y `team-01-runtime.json`. Prepara el backend desde `config/remote-state.example.tfbackend`. Activa `web.chat_enabled` en el entorno para generar la Function URL y sus permisos.

El runtime apunta a la mascota del equipo y al modelo autorizado, en la misma región. `allow_mutations` permite las acciones del wrapper; no sustituye IAM.

```bash
export AWS_CONFIG_FILE="$PWD/.local/aws-config"
export TF_DATA_DIR="$PWD/.local/tf-agent-team-01"
terraform -chdir=infra/agent init -backend-config=../../.local/agent-team-01.tfbackend
terraform -chdir=infra/agent plan -var-file=../../.local/event-config/team-01-agent.tfvars.json -out=../../.local/agent-team-01.tfplan
# Revisar antes de aplicar.
terraform -chdir=infra/agent apply ../../.local/agent-team-01.tfplan
unset TF_DATA_DIR
```

Para otro equipo, usa su archivo generado de variables, un `TF_DATA_DIR` distinto y su propia key de backend. Los nombres y el runtime ya corresponden al equipo. Registra la Function URL en `teams.json` después del deploy.

<a id="agent-estado-inicial-y-prueba"></a>

### Estado inicial y prueba

El starter del agente devuelve `AGENT_NOT_READY` hasta que exista `create_agent(model_options, runtime_options)`. La acción propia de la mascota lanza `NotImplementedError` hasta implementar `perform(pet)`. El handler registra el diagnóstico y devuelve `BACKEND_ERROR` con un `request_id`, que permite localizar el error desde la actividad de la app. Este error del starter ocurre antes de guardar cambios. Para otros errores, consulta el estado antes de reintentar.

Sigue la [guía de código](../participant-guide/agent.md) con la identidad asignada al equipo. Cada mensaje es independiente; el historial visible no se reenvía al modelo. El prompt y las tools se definen en Python. Consulta [Function URL](architecture.md#url) y [chat compartido](architecture.md#chat).

<a id="agent-actualización-y-recuperación"></a>

### Actualización y recuperación

Compara y respalda las ediciones de consola antes de aplicar código. `scripts/backup_functions.py` descarga ZIPs y verifica la cuenta, la revisión y los hashes; las capas y los datos se conservan por separado.

`workload.package_overrides` en `infra/pets` conserva un ZIP de mascota por equipo. `agent.builder_source_path` selecciona un constructor revisado, como un checkpoint, sin editar el starter público. Ninguna opción captura automáticamente futuras ediciones de consola.

Ante un timeout de una acción, consulta el estado antes de repetirla. Restaurar una función requiere un paquete compatible y autorización para reemplazar el código.

<a id="agent-retirar-un-agente"></a>

### Retirar un agente

Guarda el trabajo y retira el acceso. Inicializa el mismo backend y `TF_DATA_DIR`; genera un plan con `plan -destroy -var-file=... -out=...` y comprueba que retire solo el agente elegido. Aplica ese plan y retira sus referencias de permisos y destinos. No borres tablas para reiniciar el ejercicio.

<a id="release"></a>

## Deploy y recuperación de la app

**Terraform administra los recursos AWS**. Los scripts usan **SSM para instalar y actualizar el software del servidor**. Make reúne los comandos de ambos pasos. Revisa los cambios de infraestructura y de software por separado.

El flujo incluye la infraestructura del hosting, el proxy, la inicialización del secreto, la instalación del login y la actualización de la app compartida mediante `make shared-plan` y `make shared-apply`. La aplicación SAML de Identity Center y DNS siguen siendo pasos manuales documentados.

<a id="release-configurar-un-entorno"></a>

### Configurar un entorno

Instala Terraform, GNU Make y las dependencias Python mediante `uv sync --locked`. Usa la [configuración común](../config/README.md) para generar las variables y los runtimes. Prepara los backends por separado y completa los datos del deploy para generar `proxy.json`; cada entorno necesita sus propias keys, cuentas, subdominio e instancia.

Configura `AWS_CONFIG_FILE` y renueva SSO. Make busca los archivos operativos en `.local/`; puedes cambiar esa ruta con `LOCAL_DIR`. Para otro entorno pasa además `TF_ROOT`, `TFVARS`, `BACKEND`, `PLAN` y `PROXY_CONFIG`.

<a id="release-crear-infraestructura"></a>

### Crear infraestructura

```bash
make infra-init
make infra-plan
# Revisa recursos, cuenta, costes y destrucciones antes de continuar.
make infra-apply
```

`infra-apply` ejecuta exclusivamente el plan guardado; no genera otro plan ni hace el deploy del software. La key debe ser exclusiva del stack; revisa siempre los cambios antes de aplicar. Obtén `terraform -chdir=infra/ui-host output hosting`, copia su instancia/nombre a la configuración privada del proxy y crea el registro DNS correspondiente según [hosting](infrastructure.md#hosting). Comprueba que DNS resuelve a la IP reservada.

<a id="release-primera-instalación-del-proxy"></a>

### Primera instalación del proxy

```bash
make test
make proxy-plan MODE=install
make proxy-apply MODE=install
make proxy-result COMMAND_ID=ID_DEVUELTO
make proxy-verify
```

El instalador rechaza archivos preexistentes. Si una primera instalación queda incompleta, no la repitas ni fuerces un update; revisa el command ID, conserva los archivos y recupera el host con intervención del organizador o recrea únicamente ese host con un plan revisado. La recuperación automática descrita abajo corresponde a actualizaciones de una instalación completa.

`proxy-apply` devuelve un command ID, no una confirmación de éxito. Consulta `proxy-result` hasta un estado terminal; requiere `Success` con `ResponseCode=0`, además de `proxy-verify`. Ante timeout o resultado desconocido, consulta el mismo ID; no vuelvas a enviar el deploy automáticamente. SSM puede tardar en mostrar una invocación recién creada.

El script de consulta devuelve código 0 para éxito, 2 mientras la operación sigue pendiente y 1 para fallo terminal; Make puede representar cualquier salida no exitosa como su propio código 2. `proxy-verify` comprueba la ruta configurada; mantenimiento exige 503 y su texto; login exige el HTML de Streamlit y health check 200, además de TLS válido, redirección HTTP y ausencia de caché.

<a id="release-publicar-el-login-aislado"></a>

### Habilitar el login aislado

Primero instala y verifica `workshop-login` según [login](infrastructure.md#login), manteniendo la política deshabilitada y sin miembros. Cambia `route` en la configuración privada del proxy a `login` y sigue la secuencia de actualización con fingerprint revisado de abajo. El valor omitido o `maintenance` conserva la página de mantenimiento; no se aceptan destinos arbitrarios.

La plantilla de login envía tráfico únicamente a `127.0.0.1:8501`, sin abrir ese puerto al exterior; [Caddy admite WebSockets en reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). La comprobación HTTP no demuestra el flujo OIDC/SAML; abre el sitio, pulsa **Iniciar sesión** y prueba con un usuario asignado a la aplicación; con la política deshabilitada debe regresar a un aviso de acceso no habilitado. Verifica después el perfil federado en Cognito antes de asignar su `sub` al equipo.

Prueba también **Cerrar sesión** y comprueba que regresa al dominio de la app. Ese dominio debe coincidir con la URL de logout del cliente Cognito. La sesión del portal de Identity Center se administra por separado; para cambiar de usuario, cierra también esa sesión o usa otra sesión privada del navegador.

Para volver a mantenimiento, selecciona `route: "maintenance"` y realiza otra actualización revisada, o restaura el backup anterior y ajusta la configuración local para que `proxy-verify` compruebe la ruta restaurada. Antes de detener o eliminar el servicio de login, devuelve el proxy a mantenimiento y verifica HTTPS.

<a id="release-actualizar-sin-sobrescribir-cambios-desconocidos"></a>

### Actualizar sin sobrescribir cambios desconocidos

1. Guarda la revisión del repo/config que vas a usar en el deploy; fija la versión y el SHA-256 del binario oficial, no `latest`.
2. Ejecuta `make proxy-status` y consulta su command ID con `make proxy-result COMMAND_ID=...`.
3. Revisa los hashes del binario, del Caddyfile y del servicio; conserva su `fingerprint` como evidencia del estado que aceptas reemplazar.
4. Revisa los cambios locales y ejecuta.

```bash
make proxy-plan MODE=update EXPECTED=HUELLA_REVISADA
make proxy-apply MODE=update EXPECTED=HUELLA_REVISADA
make proxy-result COMMAND_ID=ID_DEVUELTO
make proxy-verify
```

El plan del proxy muestra un resumen y el SHA-256 del comando que se ejecutará. Es distinto de un plan guardado de Terraform. Conserva las fuentes y la configuración entre la revisión y el apply. `EXPECTED` comprueba que el estado remoto siga siendo el revisado; no firma los archivos locales.

La actualización guarda un backup antes de reemplazar la versión. Si falla el reinicio, intenta restaurar la versión anterior. Revisa el resultado para confirmar la recuperación o localizar el backup si requiere intervención manual. Conserva los certificados y el contenido de `/var/lib/caddy`.

El deploy reinicia el servicio y provoca una interrupción breve. Un corte eléctrico o una finalización forzada pueden requerir recuperación manual desde el backup. Si SSM termina correctamente pero falla HTTPS, consulta el estado y decide si debes restaurar la versión anterior.

<a id="release-volver-a-un-respaldo"></a>

### Volver a un backup

Cada actualización devuelve `backup`, por ejemplo `release-abcd1234`, ubicado en `/var/lib/workshop-proxy-backups/` con permisos restringidos. No contiene certificados, secretos ni datos de mascotas y no sustituye un backup fuera del host.

```bash
make proxy-status
make proxy-result COMMAND_ID=ID_DE_STATUS
make proxy-plan MODE=rollback EXPECTED=HUELLA_ACTUAL BACKUP=release-abcd1234
make proxy-apply MODE=rollback EXPECTED=HUELLA_ACTUAL BACKUP=release-abcd1234
make proxy-result COMMAND_ID=ID_DEVUELTO
make proxy-verify
```

El rollback verifica el manifiesto y crea un nuevo backup del estado reemplazado. Si detecta drift o corrupción, no continúa. No restaures infraestructura con estos comandos; Terraform requiere su propio plan. Los backups locales se pierden al eliminar el disco; expórtalos antes de destruir el host si necesitas conservarlos.

<a id="release-inicializar-el-secreto-del-login"></a>

### Inicializar el secreto del login

Tras aplicar el bloque opcional `login_secret` del hosting, prepara la configuración privada y ejecuta `make login-secret-plan` seguido de `make login-secret-init` según [la guía de acceso](infrastructure.md#login-preparar-el-secreto-del-login). El preview no contacta AWS; la inicialización exige un secreto sin versiones existentes. No uses estos comandos para rotar secretos o solucionar un fallo de federación mediante sobrescritura.

<a id="release-evidencia-y-límites"></a>

### Evidencia y límites

Para instalar el login una primera vez sin cambiar el proxy, usa `make login-plan` y `make login-install` según [la guía de acceso](infrastructure.md#login-instalar-el-servicio-aislado); su estado inicial deniega todos los equipos. Este instalador rechaza rutas anteriores. Las actualizaciones de la app usan el [release compartido](deployment.md#card-actualización-y-recuperación-del-servicio), con revisión del fingerprint y un backup del servicio.

En cada deploy, guarda la revisión del código, la cuenta, la instancia, los hashes del plan y del estado remoto, el command ID, el resultado, el backup y la comprobación HTTPS. Excluye tokens, contraseñas y secretos. `proxy-status` revisa archivos mediante SSM; usa también `proxy-verify` para comprobar el sitio.

Prueba una actualización y su recuperación en el entorno de ensayo antes del evento. Verifica el HTTPS, el login y el acceso a las mascotas después de cada operación.

<a id="card-actualización-y-recuperación-del-servicio"></a>

## Actualización y recuperación del servicio

```bash
make shared-status
make proxy-result COMMAND_ID=ID_DEVUELTO
make shared-plan MODE=update EXPECTED=HUELLA_DEL_SERVICIO CARD_CONFIG=.local/event-config/shared-card.json
make shared-apply MODE=update EXPECTED=HUELLA_DEL_SERVICIO CARD_CONFIG=.local/event-config/shared-card.json
make proxy-result COMMAND_ID=ID_DEVUELTO
make proxy-verify
```

Usa el fingerprint devuelto por `shared-status`, que corresponde al servicio de la app. Los releases se conservan en `/opt/workshop-login-releases/` y sus backups en `/var/lib/workshop-login-backups/`.

El release reutiliza las dependencias instaladas. Conserva sin cambios las versiones guardadas y el entorno compartido para poder recuperar el servicio.

El deploy reinicia el servicio. Si falla el reinicio o el health check, intenta restaurar la versión anterior. Revisa el resultado y prueba el login y la lectura de la mascota antes de darlo por terminado. Un corte abrupto puede requerir recuperación manual.

Para restaurar una versión retenida, consulta el fingerprint actual y ejecuta `shared-plan` y `shared-apply` con `MODE=rollback`, `EXPECTED` actual y `BACKUP=release-XXXXXXXX` devuelto por este actualizador, no por el proxy. Consulta el resultado y comprueba el HTTPS y el login nuevamente. El rollback no retira permisos IAM ni borra versiones; esas operaciones requieren planes independientes. Verifica la recuperación completa en ensayo, incluido el login federado.

<a id="card-retirada"></a>

### Retirada

Devuelve primero la aplicación al login aislado o el proxy a mantenimiento y verifica el sitio; deshabilita la política de acceso. Retira los equipos de `pet_cards`, revisa y aplica el plan para eliminar únicamente roles y políticas de lectura. No elimines las tablas de participantes mediante este stack; el archivo de destinos y los backups privados se retiran al destruir el host o mediante una operación explícita posterior.
