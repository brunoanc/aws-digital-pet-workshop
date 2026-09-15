# Infraestructura y acceso

Preparación de las cuentas, el state, los permisos, el servidor y la autenticación. Para seguir el orden completo del taller, usa la [guía del organizador](../organizer-guide/README.md).

## Contenido

- [Bootstrap y state](#bootstrap)
- [Control y presupuesto](#control)
- [Permisos de participantes](#access)
- [Hosting de la web](#hosting)
- [Login federado](#login)

<a id="bootstrap"></a>

## Bootstrap y state

<a id="bootstrap-alcance"></a>

### Alcance

El stack `bootstrap` crea un bucket S3. Configura el bloqueo de acceso público, la propiedad sin ACL, el versionado, el cifrado SSE-S3 y una política que exige HTTPS.

El state registra los recursos que administra Terraform y puede contener datos sensibles. Los demás stacks usan el bucket con keys distintas y bloqueo S3. Separa el ensayo y el evento con cuentas y keys propias, usando el mismo código Terraform.

El stack `bootstrap` guarda su state localmente, fuera del bucket que crea. Después de cada apply, conserva una copia cifrada en otra ubicación. Trabaja con una sola copia activa; este state local carece de bloqueo remoto entre operadores.

<a id="bootstrap-requisitos"></a>

### Requisitos

1. Cuenta administradora de AWS ya creada, asegurada con MFA, y acceso administrativo temporal mediante IAM Identity Center. No usar root para Terraform.
2. AWS CLI v2 y un perfil SSO que apunte a esa cuenta.
3. Terraform 1.15.x. El provider AWS 6.x está fijado en `.terraform.lock.hcl`. Prueba los cambios de dependencias antes de usarlos en el evento.
4. Revisa la facturación y habilita alertas de presupuesto. Las alertas avisan del consumo, pero no lo detienen. Incluye el almacenamiento y las solicitudes S3 en el cálculo de costos.

<a id="bootstrap-configurar"></a>

### Configurar

Crea `.local/` en la raíz del repo y copia los archivos de configuración.

- Genera `.local/event-config/bootstrap.tfvars.json` con la [configuración común](../config/README.md).
- `config/bootstrap.example.tfbackend` → `.local/bootstrap.tfbackend`.

Sustituye la cuenta, el perfil, la región, el nombre globalmente único del bucket y las etiquetas. En el backend usa una **ruta absoluta** a `.local/bootstrap.tfstate` en tu equipo. Los IDs de cuenta siempre van entre comillas para conservar los ceros iniciales.

Usa el archivo AWS CLI habitual o, si tienes perfiles separados para el taller, establece `AWS_CONFIG_FILE` a su ruta absoluta antes de ejecutar AWS CLI y Terraform. No pongas contraseñas, claves ni tokens SSO en los archivos de Terraform.

El backend y el provider se configuran por separado; los backends no admiten referencias a variables Terraform. Para los futuros estados S3 hay una plantilla `config/remote-state.example.tfbackend`; usa `mascotas/control.tfstate`, `mascotas/rehearsal.tfstate` y `mascotas/live.tfstate` en archivos distintos. El backend usará el perfil administrador; el provider de cada entorno usará el perfil de su cuenta miembro. [Configuración del backend S3](https://developer.hashicorp.com/terraform/language/backend/s3).

<a id="bootstrap-inicializar-y-probar"></a>

### Inicializar y probar

Ejecuta desde la raíz del repo.

```bash
terraform -chdir=infra/bootstrap init -backend-config=../../.local/bootstrap.tfbackend
terraform fmt -check -recursive infra
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/bootstrap test
```

`init` descarga el provider; `validate` y las pruebas se ejecutan localmente con un provider simulado. El `command = apply` dentro de las pruebas solo aplica a recursos simulados. Esto comprueba la configuración, no los permisos reales ni la disponibilidad de los nombres. [Pruebas con providers simulados](https://developer.hashicorp.com/terraform/language/tests/mocking).

<a id="bootstrap-revisar-antes-de-crear"></a>

### Revisar antes de crear

Inicia sesión con el perfil que elegiste y verifica la cuenta (sustituye el perfil de ejemplo).

```bash
aws sso login --profile workshop-management
aws sts get-caller-identity --profile workshop-management
terraform -chdir=infra/bootstrap plan -var-file=../../.local/event-config/bootstrap.tfvars.json -out=../../.local/bootstrap.tfplan
terraform -chdir=infra/bootstrap show ../../.local/bootstrap.tfplan
```

El ID debe coincidir con `management_account_id`; el provider tiene `allowed_account_ids` para rechazar otra cuenta. Para un deploy nuevo esperamos **6 adiciones, 0 cambios y 0 destrucciones**. Solo recursos S3 en la cuenta administradora. Si ya existe el bucket, detente; no fuerces su sustitución ni cambies protecciones. Revisa la propiedad e importa cada recurso correspondiente si se decide adoptarlo.

Aplica el plan una vez revisado y aprobado.

```bash
terraform -chdir=infra/bootstrap apply ../../.local/bootstrap.tfplan
terraform -chdir=infra/bootstrap output
terraform -chdir=infra/bootstrap plan -var-file=../../.local/event-config/bootstrap.tfvars.json
```

El último plan debe quedar sin cambios. Comprueba en S3 el bloqueo público, el versionado, el cifrado y la política TLS. Guarda una copia cifrada del state antes de continuar con los demás stacks.

<a id="bootstrap-límites-de-protección"></a>

### Límites de protección

- `prevent_destroy` impide que Terraform destruya/reemplace el bucket mientras su bloque siga presente. No impide borrados desde la consola ni protege si alguien elimina deliberadamente su configuración.
- `force_destroy = false` evita el vaciado automático. Versionado ayuda a recuperar objetos; no es una copia inmutable.
- El bucket no concede acceso a participantes ni cuentas miembro. Los permisos administrativos existentes de la cuenta siguen aplicando; no se pretende aislarlo de sus administradores.
- No hay caducidad automática de versiones del estado, para preservar recuperación. Revisar almacenamiento a largo plazo.

<a id="bootstrap-limpieza-y-recuperación"></a>

### Limpieza y recuperación

**Conserva este root, su estado y el bucket después del taller.** Se elimina la infraestructura de aplicación por separado; no recorras todos los roots con un bucle de `destroy`.

Si pierdes el estado local, no hagas un apply a ciegas. Recupera la copia cifrada o importa el bucket y sus cinco configuraciones tras comprobar la cuenta y los recursos exactos.

Para retirar definitivamente el backend, primero termina o migra todos los estados consumidores, conserva los backups necesarios y verifica que ningún organizador siga utilizándolo. En una revisión independiente se retira `prevent_destroy`, se vacía **únicamente ese bucket verificado**, incluidas versiones y marcadores, y se revisa un plan de destrucción explícito.

<a id="bootstrap-publicar"></a>

### Publicar

El state y la configuración real pueden contener datos sensibles. Conserva sus backups con acceso restringido y exclúyelos de cualquier distribución del proyecto.

<a id="control"></a>

## Control y presupuesto

Este root administra un presupuesto mensual en USD en la cuenta administradora. Opcionalmente incorpora [grupos, permisos de equipos y una SCP de emergencia](infrastructure.md#access) mediante `participant_access`.

<a id="control-configuración"></a>

### Configuración

Completa primero el [bootstrap](infrastructure.md#bootstrap). Usa el archivo generado `.local/event-config/control.tfvars.json` y copia `config/remote-state.example.tfbackend` a `.local/control.tfbackend`. Configura el bucket real y una key exclusiva de control. El backend y el provider deben utilizar la cuenta administradora y sesiones temporales SSO.

Configura el nombre, el importe, las alertas, los destinatarios y las etiquetas. El presupuesto cuenta todo el consumo de la organización, sin filtros por proyecto. Está pensado para una organización dedicada al taller. Las alertas se envían cuando el gasto real supera el umbral. El presupuesto se reinicia cada mes y no detiene el consumo.

El cálculo incluye los impuestos y las suscripciones. Los créditos y reembolsos no reducen el consumo registrado. Comprueba también que los destinatarios reciben las alertas por correo.

<a id="control-crear-o-adoptar"></a>

### Crear o adoptar

- Para un presupuesto nuevo, usa `import_existing = false` y un nombre que no esté en uso.
- Para adoptar uno existente, usa `import_existing = true`, su nombre exacto, los mismos importes, alertas, destinatarios y etiquetas, y las fechas actuales en UTC (`YYYY-MM-DD_hh:mm`). Terraform usa el identificador `AccountID:BudgetName`. Si no existe, la importación falla; no lo crea como alternativa. [Importación del presupuesto](https://registry.terraform.io/providers/hashicorp/aws/6.64.0/docs/resources/budgets_budget#import).

No uses `ignore_changes` para ocultar diferencias durante una importación. Revisa y resuelve cualquier cambio propuesto antes del apply.

Desde la raíz del repo, con los perfiles SSO autenticados.

```bash
terraform -chdir=infra/control init -backend-config=../../.local/control.tfbackend
terraform -chdir=infra/control validate
terraform -chdir=infra/control test
terraform -chdir=infra/control plan -var-file=../../.local/event-config/control.tfvars.json -out=../../.local/control.tfplan
terraform -chdir=infra/control show ../../.local/control.tfplan
```

Al importar un presupuesto sin cambios, el plan debe mostrar **1 importación, 0 adiciones, 0 cambios y 0 destrucciones**. Al crear uno nuevo, debe mostrar 1 adición. La importación se guarda en el state durante el apply.

Después de revisar el plan.

```bash
terraform -chdir=infra/control apply ../../.local/control.tfplan
terraform -chdir=infra/control plan -var-file=../../.local/event-config/control.tfvars.json
```

El último plan debe mostrar cero cambios. Mantén `import_existing = true` si adoptaste un presupuesto; una vez registrado, Terraform no lo vuelve a importar. Conserva el estado S3 versionado y su configuración privada. No publiques el estado; contiene destinatarios, entre otros datos.

Para pruebas sin AWS en una copia limpia, ejecuta `terraform -chdir=infra/control init -backend=false`, seguido de `validate` y `test`. Las pruebas usan un provider simulado; no validan importación real ni entrega de correo.

<a id="control-limpieza"></a>

### Limpieza

Conserva el presupuesto mientras llegan los cargos tardíos del evento. `prevent_destroy` evita borrarlo o reemplazarlo desde Terraform mientras su bloque siga presente. No ejecutes `destroy` de todo control como rutina de cierre; retira los permisos y los bloqueos según la [guía de acceso](infrastructure.md#access).

Si decides dejar de monitorear costos después de revisar la factura, su eliminación es una operación separada; revisa los recursos del estado, retira la protección explícitamente y revisa un nuevo plan antes de borrar el presupuesto. No se cierra ninguna cuenta ni se elimina el bucket de estado.

<a id="access"></a>

## Permisos de participantes

Este bloque extiende `infra/control`. Crea grupos inicialmente **vacíos**, permission sets limitados, sus políticas y asignaciones a una cuenta miembro. Opcionalmente administra membresías explícitas de usuarios existentes.

<a id="access-prerrequisitos-y-configuración"></a>

### Prerrequisitos y configuración

Revisa primero [control](infrastructure.md#control). La región de su provider (`region`) debe ser la región de IAM Identity Center, aunque `workload_region` sea distinta. El backend S3 tiene su propia región. Configura los valores de `instance_arn` e `identity_store_id` de la misma instancia organizacional. Nunca uses la cuenta administradora como entorno participante.

Completa `identity_center` en `environment.json` y los equipos en `teams.json`. El generador incluye `participant_access` y las membresías en `control.tfvars.json`. Usa ese archivo completo en cada plan de control.

Cada equipo necesita un grupo, un permission set y nombres de recursos. La tabla y la función deben usar `resource_name`; el grupo de logs será `/aws/lambda/RESOURCE_NAME`. Usa nombres nuevos para evitar mezclar el lab con datos existentes. Reserva el prefijo `DP-` para participantes, nunca para administradores.

`session_hours` define la duración de las sesiones AWS, entre 1 y 12 horas. El ejemplo usa 4 horas. Configura el MFA y la sesión del portal por separado. `model_id` admite modelos Amazon Nova de invocación directa. Para usar perfiles de inferencia entre regiones u otro proveedor, revisa los permisos y las validaciones, y prueba el cambio antes del evento.

<a id="access-contrato-de-permisos"></a>

### Permisos del equipo

- DynamoDB permite consultar y editar datos de la tabla propia, incluidas operaciones PartiQL del editor. No crear/borrar tablas ni exportar copias.
- Lambda permite consultar, invocar y actualizar **código** de la función propia. Sin `iam:PassRole`, cambio de configuración/rol ni creación de funciones.
- Logs permite leer streams y eventos de la función propia. Sin borrar registros.
- Bedrock permite listar catálogo e invocar únicamente el modelo aprobado en la región del entorno.
- Algunas listas de consola requieren `Resource: "*"` y pueden mostrar nombres de recursos de otros equipos, pero no su contenido. Los demás permisos usan los ARNs del equipo y se limitan a la región del entorno.

Comprueba las pantallas de consola con una identidad participante antes del evento. Documenta cualquier permiso adicional; no agregues FullAccess para ocultar errores. Los eventos de Lambda Test pertenecen a la función de mascota o agente según el paso.

Los participantes pueden editar los datos ficticios de su tabla y el código de su función. Limita el rol de ejecución a esa tabla y sus logs. Este entorno compartido es educativo; usa solo datos ficticios y evita tratarlo como aislamiento entre usuarios hostiles.

<a id="access-revisar-y-desplegar"></a>

### Revisar y hacer el deploy

Con sesión SSO administrativa y desde la raíz.

```bash
terraform -chdir=infra/control init -backend-config=../../.local/control.tfbackend
terraform -chdir=infra/control validate
terraform -chdir=infra/control test
terraform -chdir=infra/control plan -var-file=../../.local/event-config/control.tfvars.json -out=../../.local/access.tfplan
terraform -chdir=infra/control show ../../.local/access.tfplan
```

Comprueba los grupos, permission sets, políticas y asignaciones previstos para tus equipos. Al añadir acceso, el presupuesto debe permanecer sin cambios. Revisa la cuenta, los nombres y los ARNs, y comprueba que no haya cambios en roles administrativos antes de aplicar el plan aprobado.

Antes de dar acceso a participantes, crea dos usuarios de prueba y crea sus recursos. Asigna cada usuario a su equipo. Con sesiones limpias, comprueba que puede acceder a su equipo y que el acceso al otro se rechaza.

<a id="access-membresías-de-identidades-existentes"></a>

### Crear usuarios y asignar equipos

Desde la cuenta administradora, abre Identity Center en la región configurada para el taller. Cada participante o equipo necesita un usuario del directorio. Las cuentas AWS del entorno se preparan por separado.

1. Abre **IAM Identity Center → Users → Add user**.
2. Completa el username, el correo, el nombre y el apellido. Puedes usar el correo como username.
3. Selecciona **Send an email to this user with password setup instructions**.
4. Continúa con los grupos sin seleccionar y confirma la creación del usuario. Terraform administrará la membresía del equipo.
5. Abre la invitación que llegó al correo y completa la creación de la contraseña.
6. Vuelve a **Users**, abre el usuario y registra su `UserId` en el inventario privado.

Si usas un correo con forwarding para un equipo, comprueba que recibe las invitaciones y los mensajes de recuperación. El forwarding recibe los correos; el usuario se crea en Identity Center.

Añade cada UserId a `identity_center_user_ids` en el equipo correspondiente de `teams.json`. Genera otra carpeta y usa su `control.tfvars.json` para revisar las membresías. Un UserId pertenece a un solo equipo.

Revisa el plan; debe añadir únicamente las membresías elegidas (`aws_identitystore_group_membership`) y conservar los permission sets y el presupuesto. Cuando los recursos estén listos, activa `identity_center.assignments_enabled` en `environment.json`, genera la configuración y revisa el plan de las asignaciones a la cuenta AWS. Después del apply, verifica los grupos y entra al portal con cada usuario en sesiones separadas. Comprueba la activación de la contraseña y la política de MFA desde Identity Center.

Completa también la [asignación a la aplicación SAML](#login-asignar-usuarios-a-la-aplicación) y la [asociación del perfil de Cognito al equipo](#login-asignar-equipos-después-de-verificar-la-federación).

Para probar solo `team-00`, configura `identity_center.assignment_teams` con `["team-00"]` y activa `identity_center.assignments_enabled` en `environment.json`. Registra el UserId del usuario de prueba únicamente en ese equipo. El plan debe añadir su membresía y su asignación a la cuenta AWS; los otros equipos conservan sus grupos y permission sets, con las asignaciones cerradas. Después del apply, entra al portal SSO con el usuario de prueba y comprueba la cuenta y el permission set en **AWS accounts**. La [configuración de equipos](../config/README.md#equipos-y-acceso) explica cómo ampliar o cerrar la lista.

Revisa también las membresías, grupos y asignaciones creados fuera de Terraform para detectar permisos adicionales. Si la membresía ya existe, impórtala antes de aplicar; no intentes crearla de nuevo. Para revocar las membresías administradas, elimina sus entradas del mapa y revisa el plan, manteniendo la SCP activa durante la ventana de expiración descrita abajo.

<a id="access-interruptor-de-emergencia"></a>

### Interruptor de emergencia

Cada entorno crea una SCP que deniega acciones a los roles SSO participantes y a los roles de ejecución de agentes registrados mediante `agent_resource_name`. `emergency_deny = false` deja la política sin adjuntar; `true` la adjunta a la cuenta miembro. Cierra también el acceso de la web desde su política de autorización.

Antes del evento, activa el interruptor en ensayo mediante un plan revisado, comprueba que una **sesión de alumno ya abierta** pierde acceso y que el administrador conserva el suyo. Reactívala solo tras registrar resultados. Las pruebas simuladas de Terraform no demuestran ese comportamiento real.

Para cerrar el acceso, activa el bloqueo y comprueba que funciona. Después configura `assignments_enabled = false` y aplica el plan para retirar las asignaciones. Conserva los grupos, los permission sets y la SCP durante la expiración de sesiones.

Retira por separado las membresías e identidades del evento. Mantén la SCP adjunta al menos 12 horas después de impedir nuevas sesiones. Durante ese tiempo conserva `emergency_deny = true`, el entorno y los nombres de permission sets; cambiarlos podría dejar credenciales válidas sin bloqueo. Después de comprobar la expiración, retira los recursos de acceso y conserva el presupuesto. [Revocación de sesiones](https://docs.aws.amazon.com/singlesignon/latest/userguide/prereqs-revoking-user-permissions.html).

<a id="access-protección-de-las-cuentas"></a>

### Protección de las cuentas

Antes de añadir políticas, inventaría SCP de raíz, OU y cuentas. Si ya existe una denegación heredada de `organizations:LeaveOrganization` y `account:CloseAccount`, consérvala; este módulo no la recrea ni la importa. Para una organización nueva, esa protección sigue siendo un prerrequisito administrativo. No pruebes su funcionamiento intentando cerrar una cuenta. Las SCP no restringen la cuenta administradora. [Buenas prácticas de administración](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_best-practices_mgmt-acct.html).

<a id="hosting"></a>

## Hosting de la web

`infra/ui-host` crea la red, instancia Amazon Linux 2023, Elastic IP y roles del servidor; también puede crear el secreto de login y los permisos por equipo cuando se configuran. Los scripts de deploy instalan Streamlit y Caddy.

<a id="hosting-preparación"></a>

### Preparación

1. Completa las opciones de `web` en `environment.json` y genera `ui-host.tfvars.json`.
2. Consulta el parámetro público `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` en SSM y fija su AMI en config; Terraform comprueba que pertenece a Amazon y corresponde a AL2023 x86_64.
3. Inicializa con un backend privado y una key exclusiva; ejecuta `validate`, `test` y `plan` antes de aplicar.
4. Confirma que el plan se limita a los recursos del hosting.
5. Tras aplicar, consulta el output `hosting` y verifica que el nodo aparezca **Online** en Systems Manager.

La instancia usa IMDSv2, disco gp3 cifrado y CPU credits Standard; al agotar créditos puede ralentizarse, por lo que el tamaño necesita pruebas de carga. No hay clave SSH, puerto 22 abierto, NAT Gateway ni balanceador. La única salida de Internet permitida es TCP 443; DNS y sincronización horaria usan servicios de la VPC/link-local. Las entradas 80/443 se reservan para HTTPS y validación de certificados.

La dirección pública proviene de una Elastic IP administrada por Terraform. Al actualizar el hosting, comprueba que el plan conserve la instancia, el disco y la asociación de esa IP.

El rol base usa `AmazonSSMManagedInstanceCore`; `login_secret` agrega lectura del secreto concreto y `pet_cards` permite asumir los roles limitados de cada equipo. Los permisos de ficha y agente se explican en [chat compartido](architecture.md#chat). Quien puede enviar comandos SSM controla el host, así que ese acceso se reserva a organizadores. El servicio de la app corre sin root; esto no convierte el host en un aislamiento frente a una instancia comprometida.

<a id="hosting-dns-y-https"></a>

### DNS y HTTPS

Antes de crear DNS, comprueba que no exista un A, AAAA o CNAME del mismo nombre. En tu proveedor DNS crea un registro **A** del subdominio del entorno a `hosting.public_ip`, con TTL corto durante las pruebas. Conserva los registros de otros servicios.

DNS solo apunta al servidor; después instala el proxy HTTPS y el login en loopback. No expongas el puerto Streamlit. Mantén cerrado el acceso hasta validar la autenticación, las autorizaciones y las cuotas.

<a id="hosting-proxy-de-mantenimiento"></a>

### Proxy de mantenimiento

Tras verificar DNS, `scripts/deploy_proxy.py` instala Caddy desde su release oficial, verificando el SHA-256 configurado antes de extraer el binario. Registra `deployment.instance_id` en el entorno y genera `proxy.json`. Ejecuta primero sin `--apply`; después añade esa opción para instalar mediante SSM. El script comprueba la cuenta, el ID, el nombre y el estado del host y devuelve un command ID; hay que revisar su resultado en SSM antes de dar la instalación por terminada.

Las plantillas de `hosting/` crean un servicio con usuario dedicado, sin root, y certificados persistidos en `/var/lib/caddy`; no se habilita el API administrativo ni el log de peticiones. La configuración inicial redirige HTTP a HTTPS y devuelve 503 con un mensaje de preparación; no enruta al chat ni al login. La instalación rechaza archivos anteriores; los modos update y rollback gestionan instalaciones completas con fingerprint revisado, backup y recuperación según el [flujo unificado](deployment.md#release).

Comprueba desde fuera del servidor el certificado TLS y la respuesta 503 sin desactivar la validación de certificados. Que el servicio systemd esté activo no basta para confirmar HTTPS. El instalador no transporta secretos ni credenciales en comandos SSM; solo las plantillas públicas y el hash del binario. Instalación del proxy, [instalación oficial de Caddy](https://caddyserver.com/docs/install).

<a id="hosting-coste-y-retirada"></a>

### Coste y retirada

Presupuesta instancia encendida, disco e IPv4 por separado, además de transferencia, logs, secretos e inferencia cuando existan. No supongas créditos ni capa gratuita. Apagar EC2 detiene su cómputo, pero conserva cargos por el disco y la IP reservada.

Antes de destruir la instancia, guarda la configuración y los archivos que necesites. El disco raíz se elimina junto con ella. Revisa el plan y retira el registro DNS. Este stack elimina el host, su red y sus roles, y libera la Elastic IP. Cognito y las mascotas se gestionan por separado. Si recreas el host, puede recibir otra IP. Conserva el backend de Terraform para mantener el registro de los recursos.

Referencias, [roles de Systems Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-instance-permissions.html), [Python en Amazon Linux](https://docs.aws.amazon.com/linux/al2023/ug/python.html), [EC2 T3](https://aws.amazon.com/ec2/instance-types/t3/), [IPv4](https://aws.amazon.com/vpc/pricing/) y [EBS](https://aws.amazon.com/ebs/pricing/).

<a id="login"></a>

## Login federado

La instalación inicial muestra solo el acceso, y el deploy del [chat compartido](architecture.md#chat) agrega ficha y agente después de validar permisos.

<a id="login-asignar-equipos-después-de-verificar-la-federación"></a>

### Asignar equipos después de verificar la federación

Con la sesión de organizador, consulta el perfil de Cognito y compara su proveedor SAML e identidad con el usuario de Identity Center. El correo por sí solo no concede acceso. Añade el `sub` a `cognito_subjects` del equipo correcto en `teams.json` y vuelve a generar `access.json`. Conserva el issuer y el cliente configurados. Define la ventana de acceso en segundos Unix y habilita solo las identidades aprobadas.

```bash
make login-access-status
make proxy-result COMMAND_ID=ID_DEVUELTO
make login-access-plan ACCESS_CONFIG=.local/event-config/access.json EXPECTED=HUELLA_REVISADA
make login-access-apply ACCESS_CONFIG=.local/event-config/access.json EXPECTED=HUELLA_REVISADA
make proxy-result COMMAND_ID=ID_DEVUELTO
```

Revisa la política y el fingerprint antes del apply; exige `Success` y código 0 después. La nueva política se aplica en la siguiente comprobación de acceso. Conserva el backup devuelto por el comando en una ubicación privada, porque contiene las asignaciones de los equipos.

Recarga el sitio y confirma el equipo mostrado. Prueba además un usuario sin asignación; debe ser rechazado. Para revocar acceso, aplica una política revisada con `enabled=false` o retira el miembro; para recuperar una versión anterior, utiliza su contenido como política candidata y el fingerprint actual mediante el mismo procedimiento. La ventana cerrada deniega comprobaciones posteriores, pero no cierra cookies ni apaga infraestructura. Retira la app pública o vuelve a mantenimiento antes de eliminar el hosting.

No renombres ni reutilices identidades SAML durante el ensayo; AWS recomienda un [NameID que no cambie](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-saml-idp.html). Verifica ese mapeo antes del evento y no confundas el `sub` de Cognito con el UUID de Identity Store.

La app usa las mismas credenciales que la consola. Streamlit se conecta a Cognito mediante OIDC, y Cognito delega el login a Identity Center mediante SAML. El perfil federado de Cognito se crea al iniciar sesión.

<a id="login-etapa-1-base-de-autenticación"></a>

### Etapa 1. Base de autenticación

Con `saml_metadata_url = null`, `infra/ui-auth` crea únicamente un user pool Lite y un dominio Cognito con hosted UI clásica. Al configurar esa URL añade el proveedor SAML y el cliente OAuth.

La configuración MFA del pool no sustituye la política de Identity Center; en este diseño, la autenticación y su MFA se realizan en el proveedor federado.

1. Completa el dominio de Cognito en `environment.json` y deja `web.saml_metadata_url` en `null`; usa el archivo generado `ui-auth.tfvars.json`.
2. Prepara un backend S3 privado con una key exclusiva de este stack.
3. Ejecuta init, validate, test y plan; revisa que solo se añadan el pool y su dominio antes de aplicar.
4. Obtén `terraform output federation_setup`; no contiene contraseñas ni secretos.

<a id="login-etapa-2-aplicación-manual-en-identity-center"></a>

### Etapa 2. Aplicación en Identity Center

Desde la cuenta administradora y la región de Identity Center.

1. Abre **IAM Identity Center → Applications → Add application**.
2. Selecciona **I have an application I want to set up → SAML 2.0**.
3. Usa un nombre descriptivo, por ejemplo **Taller de mascotas — Ensayo**.
4. Copia `acs_url` del output a **Application ACS URL** y `audience` a **Application SAML audience**; el ACS termina en `/saml2/idpresponse`, no es el callback OIDC de Streamlit.
5. Guarda el documento o URL de metadatos de Identity Center para configurar posteriormente el proveedor SAML en Cognito.
6. Abre **Attribute mappings** y configura **Subject** con `${user:subject}`, formato **persistent**. Añade `email` con `${user:email}`, formato **unspecified**.
7. Guarda los cambios y asigna primero el usuario de prueba siguiendo los pasos de la siguiente sección.

La aplicación SAML se crea desde la consola. Terraform configura el proveedor y el cliente de Cognito a partir de sus metadatos.

<a id="login-asignar-usuarios-a-la-aplicación"></a>

### Asignar usuarios a la aplicación

1. Abre **IAM Identity Center → Applications** y selecciona la aplicación del entorno.
2. Pulsa **Assign users and groups**.
3. En **Users**, selecciona el usuario de prueba y confirma con **Assign**.
4. Comprueba que aparece entre los usuarios asignados. Al preparar los participantes, repite estos pasos con las identidades aprobadas.

Una vez instalado el login, abre la web del taller y pulsa **Iniciar sesión** con ese usuario. Con el acceso de la app deshabilitado, debe aparecer "El acceso al taller no está habilitado en este momento". Ese primer login crea el perfil federado en Cognito; verifica su proveedor y su identidad antes de registrar el `sub` del equipo.

<a id="login-etapa-3-enlace-federado"></a>

### Etapa 3. Conexión federada

Configura `web.saml_metadata_url` en `environment.json` con el endpoint obtenido y genera de nuevo `ui-auth.tfvars.json`. Revisa y aplica el plan. Terraform añade el proveedor SAML y el cliente OIDC confidencial, con flujo authorization code, callback exacto `/oauth2callback` y únicamente el proveedor Identity Center habilitado. `oidc_setup` entrega la configuración sin el secreto; este permanece en el estado Terraform protegido y no debe imprimirse ni publicarse. Los atributos mapeados son editables para permitir su actualización durante la federación; el correo no autoriza acceso a equipos.

Configura los secretos de Streamlit en `.local/` y registra `issuer` y `sub` de Cognito para cada equipo. Salir de la app puede dejar abierta la sesión del portal AWS. Prueba el logout y la expiración de ambas sesiones.

Inicia sesión desde la app para conservar el flujo OIDC. Prueba la expiración, el logout y la denegación entre equipos antes de abrir el acceso.

<a id="login-ensayo-de-la-entrada-autenticada"></a>

### Ensayo de la entrada autenticada

La instalación inicial permite probar el login y confirmar el equipo autorizado. Después de verificar la federación, haz el deploy de la app compartida para mostrar la ficha y el chat.

Usa `config/login-secrets.example.toml` como plantilla si preparas los secretos manualmente. El flujo recomendado los inicializa en Secrets Manager siguiendo la siguiente sección. Habilita el acceso desde `environment.json` y aplica la política generada `access.json`.

El registro guarda el issuer, client ID, ventana del evento en segundos Unix UTC, duración máxima y el mapa `members`. Ese mapa relaciona el `sub` de Cognito con un equipo. Verifica cada perfil después del primer login y registra su `sub`, que es distinto del UserId de Identity Center. La asignación se hace en la configuración, no por correo ni desde el navegador.

Cada entorno debe usar su propio origen HTTPS y configuración de Cognito; un subdominio de ensayo y otro para el evento, sin autorizar ambos en el mismo cliente. Cambiar `auth.app_origin` actualiza callback y salida del cliente OIDC; la URL ACS y la audiencia SAML de Identity Center se conservan.

El callback de Cognito apunta al dominio del entorno, no a localhost. Prepara el hosting, el TLS, los secretos y los permisos antes de probar el login. El chat compartido revalida el acceso y aplica límites por equipo; verifica la concurrencia prevista para el evento.

<a id="login-preparar-el-secreto-del-login"></a>

### Preparar el secreto del login

El bloque opcional `login_secret` de `infra/ui-host` crea únicamente el contenedor en Secrets Manager y concede al rol del host `GetSecretValue` sobre su ARN exacto, sin permisos de escritura ni acceso a mascotas. Su valor se inicializa fuera de Terraform; el secreto original del cliente Cognito sigue presente en el estado protegido de `infra/ui-auth`, porque ese stack crea el cliente confidencial.

1. Configura `login_secret = { name = "digital-pet-test-ui/login", recovery_window_in_days = 7 }` en los tfvars privados del hosting.
2. Revisa y aplica el plan de `infra/ui-host`; el cambio previsto añade un secreto y una política de lectura, sin reemplazar la instancia.
3. Completa `deployment.secret_arn`, `deployment.user_pool_id` y `deployment.client_id` en el entorno. Usa el ARN exacto de `terraform -chdir=infra/ui-host output -raw login_secret_arn`. Genera `login-bootstrap.json` con esos datos.
4. Ejecuta `make login-secret-plan` para un preview local y `make login-secret-init` para inicializarlo con la sesión de organizador.

Antes de escribir, el script comprueba la cuenta, el secreto y la configuración del cliente Cognito. Genera una clave para cookies y mantiene los valores sensibles en memoria hasta enviarlos a Secrets Manager. La salida muestra ARN, estado y versión. Comprueba `AWSCURRENT` antes de confirmar que terminó.

La inicialización requiere un secreto sin versiones existentes. Ante un timeout o resultado desconocido, consulta las versiones antes de repetir el comando. Ejecuta un solo inicializador a la vez y mantén deshabilitados los logs de depuración del SDK para proteger los valores sensibles.

El valor almacenado es JSON con una sección `auth`, equivalente a la plantilla TOML de Streamlit. Después de inicializarlo, instala el servicio descrito abajo para leerlo con el rol del host y preparar la configuración privada. Secrets Manager añade costes de almacenamiento y llamadas que deben incluirse en el presupuesto.

<a id="login-instalar-el-servicio-aislado"></a>

### Instalar el servicio aislado

Con el secreto preparado y SSO vigente, ejecuta `make login-plan` y revisa la cuenta, la instancia y el fingerprint. Después usa `make login-install`. Consulta el command ID con `make proxy-result COMMAND_ID=...` hasta que termine. Ante un timeout, consulta ese mismo ID antes de decidir otra acción.

El instalador prepara Python 3.13, las dependencias de `uv.lock` y el servicio `workshop-login`. Requiere acceso HTTPS a los repositorios de Amazon Linux y PyPI.

El servicio escucha en `127.0.0.1:8501`; Caddy proporciona el acceso HTTPS. La configuración se conserva en `/etc/workshop-login` y los secretos se cargan desde Secrets Manager al arrancar. Reinicia el servicio después de rotar las credenciales.

La política inicial tiene `enabled=false`, una ventana cerrada y `members={}`. Mantén cerrado el puerto 8501 al exterior y conserva las protecciones CORS y XSRF.

La primera instalación exige rutas nuevas y mantiene el proxy en mantenimiento. Conserva el command ID y revisa el estado sin imprimir secretos ni borrar rutas para reintentar. Las actualizaciones y el rollback usan el [release compartido](deployment.md#card-actualización-y-recuperación-del-servicio). Un health check válido no confirma el login SAML completo.

Para habilitar únicamente este login, selecciona `route: "login"` en la configuración privada del proxy y sigue la [actualización con backup y verificación HTTPS](deployment.md#release-publicar-el-login-aislado). Mantén deshabilitada la autorización de equipos durante la primera prueba de federación; un login correcto debe regresar al aviso de acceso no habilitado.

En una instalación nueva, comprueba el arranque, los permisos y la escucha local antes de conectar Caddy; después prueba el acceso anónimo y el login federado. Mantén el proxy en mantenimiento hasta completar esos pasos. Cognito puede crear un perfil al iniciar sesión aunque la app todavía deniegue el acceso; verifica su `sub` antes de asignarle equipo.

Referencias, [versiones Python de AL2023](https://docs.aws.amazon.com/linux/al2023/ug/python.html) y [configuración de Streamlit](https://docs.streamlit.io/develop/api-reference/configuration/config.toml).

<a id="login-retirada-de-autenticación"></a>

### Retirada de autenticación

Al finalizar, deshabilita la app compartida y retira las asignaciones SAML antes de destruir este stack. Revisa el plan; destruir el pool borra los perfiles federados y cambia sus identificadores si se recrea; los usuarios de Identity Center se conservan. Elimina la aplicación SAML manualmente y retira los secretos del cliente cuando existan. DNS y hosting tendrán su propia limpieza; no destruyas los estados o tablas de mascotas desde este stack.

El secreto pertenece al stack de hosting y se elimina con una ventana de recuperación configurada de 7–30 días, sin borrado inmediato; queda inaccesible al programar su eliminación y no debes reutilizar su nombre mientras siga pendiente. Retira también el cliente Cognito y las copias del secreto que existan en el host.

Si el host se conserva, ejecuta por SSM `systemctl disable --now workshop-login` y verifica que el servicio esté detenido, no exista un listener en 8501 y `/run/workshop-login` haya desaparecido antes de retirar su permiso sobre el secreto. No imprimas el archivo TOML para comprobar su eliminación. El código y la política privada de `/opt/workshop-login` y `/etc/workshop-login` permanecen en el disco hasta su retirada explícita o la destrucción del host; el proxy debe volver a mantenimiento antes de deshabilitar un login que ya estuviera habilitado.

<a id="login-referencias"></a>

### Referencias

- [AWS; integración de Cognito con Identity Center](https://repost.aws/knowledge-center/cognito-user-pool-iam-integration).
- [Cognito; ACS y audiencia SAML](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-integrating-3rd-party-saml-providers.html).
- [Identity Center; límite de CreateApplication](https://docs.aws.amazon.com/singlesignon/latest/APIReference/API_CreateApplication.html).
- [Streamlit; autenticación y expiración de sesiones](https://docs.streamlit.io/develop/concepts/connections/authentication).
