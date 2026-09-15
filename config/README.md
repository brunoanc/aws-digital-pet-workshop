# Configuración del entorno

El organizador mantiene dos archivos privados.

- `environment.json` reúne las cuentas, los perfiles, la región, el dominio, el modelo y las opciones de acceso.
- `teams.json` reúne los equipos, sus recursos y las identidades asignadas.

Copia los ejemplos a `.local/` y completa sus valores. Usa una AMI de Amazon Linux 2023 x86_64 disponible en la región elegida y un nombre único para el bucket y el dominio de Cognito.

```bash
mkdir -p .local
cp config/environment.example.json .local/environment.json
cp config/teams.example.json .local/teams.json
```

## Generar los archivos

Revisa primero los nombres de salida. Añade `--write` para escribirlos en una carpeta nueva.

```bash
uv run --locked python -m scripts.configure_environment \
  --environment .local/environment.json \
  --teams .local/teams.json \
  --output .local/event-config

uv run --locked python -m scripts.configure_environment \
  --environment .local/environment.json \
  --teams .local/teams.json \
  --output .local/event-config --write
```

El directorio padre debe existir. La salida tiene permisos privados y conserva las carpetas existentes. Para revisar un cambio, genera `.local/event-config-next`, compara los archivos y usa esa nueva ruta en los comandos del deploy. Conserva el directorio mientras sus variables de Terraform apunten a los runtimes que contiene.

| Salida | Uso |
| --- | --- |
| `bootstrap.tfvars.json` | Bucket del state |
| `control.tfvars.json` | Presupuesto, permisos y membresías de Identity Center |
| `pets.tfvars.json` | Recursos de todas las mascotas |
| `team-XX-agent.tfvars.json` y `team-XX-runtime.json` | Deploy y runtime de cada agente |
| `ui-host.tfvars.json` y `ui-auth.tfvars.json` | Hosting y login de la web |
| `operations.json` | Seed y operaciones sobre las mascotas |
| `team-XX-remote-agent.json` | Conexión al agente, con su URL cuando esté registrada |
| `proxy.json`, `login-bootstrap.json` y `access.json` | Configuración posterior al deploy |
| `shared-card.json` | Destinos de la web cuando se habilitan las tarjetas |

Los archivos `.tfvars.json` se pasan con `-var-file`, igual que los archivos `.tfvars`. Edita las entradas y vuelve a generar las salidas para mantener sus valores sincronizados. `layer_zip_path` se resuelve desde la raíz del repo; el generador escribe rutas absolutas para el ZIP, el fixture y los runtimes.

El Makefile usa `.local/event-config` como `CONFIG_DIR`. Para revisar otra carpeta, pasa `CONFIG_DIR=/ruta/absoluta/event-config-next`. Los backends y los planes siguen en `.local/`; también puedes indicar sus rutas con `BACKEND` y `PLAN`.

## Equipos y acceso

Cada clave de `teams.json` tiene el formato `team-01`. El nombre de la tabla y la función de mascota se deriva de `resource_prefix` y del ID del equipo. El agente añade `-agent`. El campo opcional `resource_name` permite indicar un nombre distinto para un equipo.

`identity_center_user_ids` contiene los UserIds que reciben permisos de AWS. `cognito_subjects` contiene los valores `sub` verificados que acceden a la app. Cada identidad se asigna a un solo equipo; un equipo puede tener varias identidades.

Los ejemplos dejan deshabilitadas las asignaciones de AWS y el acceso a la app. Activa `identity_center.assignments_enabled` cuando los recursos estén preparados. Define la ventana de acceso en segundos Unix y activa `access.enabled` después de verificar el login y los equipos.

`access.max_session_seconds` controla la duración de la sesión web y de los ID y access tokens de Cognito. Usa `14400` para cuatro horas. Al cambiarlo, aplica `ui-auth.tfvars.json` en Terraform y actualiza la política `access.json` del servidor. Inicia sesión de nuevo para recibir un token con la nueva duración. La ventana `opens_at` y `closes_at` puede cerrar el acceso antes. Las sesiones de la consola AWS usan `identity_center.session_hours` por separado.

Para habilitar solo un equipo piloto, añade `"assignment_teams": ["team-00"]` dentro de `identity_center` y activa `assignments_enabled`. El equipo debe existir en `teams.json`. Una lista vacía deja todas las asignaciones cerradas; al omitir la lista, el switch se aplica a todos los equipos. `assignments_enabled = false` cierra las asignaciones AWS de todo el entorno, incluida la del piloto. El acceso de la web se controla por separado con `access` y `cognito_subjects`.

## Completar los datos del deploy

Añade a `environment.json`, dentro de `deployment`, los valores reales de las salidas de Terraform.

```json
{
  "instance_id": "i-0123456789abcdef0",
  "user_pool_id": "us-east-1_EXAMPLE",
  "client_id": "exampleclient123",
  "secret_arn": "arn:aws:secretsmanager:us-east-1:444455556666:secret:dp-workshop-ui/login-AbCdEf"
}
```

`instance_id` permite generar `proxy.json`. Los tres campos del login se completan juntos para generar `login-bootstrap.json` y `access.json`. El ARN identifica el secreto; su contenido se administra con las herramientas de login.

Activa `web.cards_enabled` para crear los permisos de lectura de las tarjetas. Activa también `web.chat_enabled` para crear las Function URLs y sus permisos. Después del deploy, registra la `function_url` de cada agente en su entrada de `teams.json` y genera otra carpeta. Con el chat habilitado, `shared-card.json` se genera cuando todos los equipos tienen una URL. Comprueba los destinos contra las salidas de Terraform antes del deploy de la web.

El proxy generado empieza en `maintenance`. La apertura de la ruta de login sigue el proceso de [deploy](../docs/infrastructure.md#hosting). Revisa los límites del modelo en `model`; admite los límites del runtime, además de `model_id`, `personality` y `allow_mutations`.

Para realizar los ejercicios de cuidados y acción propia, configura `model.allow_mutations = true` antes de generar las variables y hacer el deploy de los agentes. El valor `false` permite las consultas, pero bloquea las acciones que cambian el estado.

## Backends, secretos y pruebas

Los backends conservan sus propias plantillas. Cada stack y cada agente requiere una key exclusiva. Un backend existente conserva su bucket, key y región. La región de Identity Center se puede indicar con `identity_center.region` si difiere de la región del lab. El stack de slides mantiene su configuración independiente y ACM en `us-east-1`.

`login-secrets.example.toml` sirve para el flujo de secretos manual. Los ejemplos `capacity*` corresponden a las pruebas temporales de carga; se usan únicamente durante esas pruebas.

Para un entorno existente, conserva sus configuraciones operativas hasta revisar un plan sin reemplazos inesperados. El generador deriva nombres para un entorno nuevo. Compara especialmente los nombres de hosting, Cognito, grupos y permission sets antes de adoptarlo en recursos existentes.
