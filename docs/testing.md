# Pruebas y diagnóstico

Cómo revisar la configuración, comprobar AWS y probar la capacidad del lab.

## Contenido

- [Diagnóstico del equipo](#diagnostics)
- [Pruebas de capacidad](#capacity)

<a id="diagnostics"></a>

## Diagnóstico del equipo

Ejecuta desde la raíz del repo con Python 3.13 y las dependencias de `uv.lock` instaladas.

```bash
uv run --locked python -m scripts.doctor --app-config .local/event-config/team-01-runtime.json --offline
```

Este modo revisa el entorno local y la configuración. Para comprobar AWS, usa la configuración de un equipo y una sesión SSO vigente.

```bash
uv run --locked python -m scripts.doctor --app-config .local/event-config/team-01-runtime.json --agent-config .local/event-config/team-01-remote-agent.json
```

Si tus perfiles están en un archivo separado, configura `AWS_CONFIG_FILE` con su ruta antes de ejecutar el comando.

El diagnóstico comprueba la cuenta y la configuración de las funciones. Después lee la mascota en DynamoDB y compara el resultado con una llamada `inspect` a su función Lambda. Usa una función conocida, ya que se ejecutará su código y se generará consumo de Lambda y logs.

Añade `--inference` para hacer una llamada breve al modelo. Tiene costo y usa un mensaje sin datos de la mascota ni tools. Esta opción es incompatible con `--offline`.

El reporte JSON indica `PASS`, `FAIL` o `SKIP`. Si alguna comprobación falla, el comando termina con código 1. `SKIP` significa que esa comprobación se omitió.

Los errores muestran su tipo y ocultan credenciales y mensajes internos del servicio. Si DynamoDB y `inspect` devuelven datos distintos, revisa si alguien ejecutó un cuidado durante la prueba. El diagnóstico termina sin repetir las llamadas.

El resultado solo valida el perfil usado. Repite la prueba con los roles de participantes antes del taller. Comprueba por separado el aislamiento entre equipos, la edición de código, CloudWatch, la app, la concurrencia y el recorrido completo del participante.

<a id="capacity"></a>

## Pruebas de capacidad

Ejecuta estas pruebas sobre destinos temporales, separados del entorno de participantes. Prepara la infraestructura antes de iniciar la prueba.

<a id="capacity-entradas"></a>

### Entradas

- Configuración desde `config/capacity.example.json`, con los 15 equipos de carga y lotes revisados.
- Expectativas por equipo, `pet_code_sha256`, `agent_code_sha256`, `layer_code_sha256`, `pet_timeout_seconds`, `agent_timeout_seconds`, `pet_memory_mb` y `agent_memory_mb`.
- Obtén hashes, timeouts y memoria desde los planes revisados (`source_code_hash`, `timeout`, `memory_size`). Compáralos con AWS para detectar cambios en los recursos del lab.
- Crea los recursos e inicializa las mascotas de prueba antes del preflight. Usa una sesión SSO y mantén las credenciales fuera del manifiesto.

<a id="capacity-modos"></a>

### Modos

Revisión local, sin llamadas AWS.

```bash
python -m scripts.capacity_execute --config .local/capacity.json --expected .local/capacity-expected.json
```

Preflight, solo lecturas AWS y sin inferencia.

```bash
python -m scripts.capacity_execute --config .local/capacity.json --expected .local/capacity-expected.json --preflight
```

El preflight revisa la cuenta, las cuotas, las funciones, el runtime, los hashes, las políticas IAM, las Function URLs y las mascotas. Si una política difiere de la esperada, la prueba se detiene. Revisa la diferencia antes de continuar.

Comprueba también las denegaciones IAM con usuarios reales. El preflight no cubre todas las SCP ni las políticas de recursos.

Revisa el plan y el presupuesto antes de ejecutar la prueba. Usa las mismas entradas y añade `--execute --approved-sha256 HUELLA --output DIRECTORIO_NUEVO`. Obtén el fingerprint en el modo de revisión. El fingerprint identifica lo revisado; la aprobación y el control de costos siguen siendo responsabilidad del organizador.

Cada pasada admite hasta 32 mensajes y espera al menos 60 segundos entre lotes. Verifica cada URL con la API de Lambda. Si falla una solicitud, espera a que terminen las que están en curso y detiene la prueba antes del siguiente lote. Las solicitudes fallidas quedan registradas, sin reintentos automáticos.

<a id="capacity-resultados-y-recuperación"></a>

### Resultados y recuperación

El directorio de resultados contiene `started.json`, `before.json`, un archivo por lote y `result.json`. Después de cada lote se compara el item completo de cada mascota. Cualquier cambio detiene la prueba. Las respuestas deben incluir actividad de `inspect_pet`; el texto del modelo por sí solo no basta.

Usa un directorio nuevo para cada pasada. Si el proceso se interrumpe, revisa los archivos y AWS antes de repetirla. Tras un fallo, revisa el estado y retira los recursos de prueba mediante un plan aprobado. No ejecutar dos runners con directorios diferentes a la vez; el límite de 32 es por pasada, no una cuota global persistente.

Los reportes incluyen la duración, el equipo, el resultado y el tipo de error. El agente no devuelve el consumo real de tokens ni los request IDs de Bedrock. Guarda las métricas y los logs de AWS del mismo intervalo para revisar el consumo. Trata cualquier cálculo basado solo en el reporte como una estimación.

Prueba las sesiones simultáneas de navegador por separado, porque este flujo llama al backend sin pasar por Streamlit. Al terminar, revisa un plan para retirar únicamente los recursos e identidades de prueba.
