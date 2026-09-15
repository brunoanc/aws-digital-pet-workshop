# Capturas para la presentación

Las capturas de la presentación están en `assets/screenshots/`. Para adaptar el taller, reemplázalas por imágenes de tu entorno con el contenido indicado.

| Captura | Contenido | Archivo |
|---|---|---|
| DynamoDB, edición del item | `pet_id`, `name` y `species` | `dynamodb-item.png` |
| Lambda agente, Function URL | Configuration, Function URL y botón para copiar; dirección oculta | `lambda-function-url.png` |
| Lambda agente, editor | Árbol de archivos, `agent_builder.py`, imports, `create_agent`, `BedrockModel`, `Agent`, `return agent` y Deploy. Código anterior al system prompt | `lambda-editor.png` |
| CloudWatch, error de implementación | Evento ampliado con `PET_BACKEND_ERROR`, `request_id`, `exception_type` y el último frame | `cloudwatch-error.png` |

Para CloudWatch, captura el error de la primera llamada a `custom_action`, antes de completar `perform`. En el log group de la función Lambda de la mascota, busca el `request_id` de la actividad y expande `PET_BACKEND_ERROR`. Deben verse `NotImplementedError` y el último frame con `custom_action.py`, `perform` y la línea. Si la acción ya está implementada, conserva el código y usa una ejecución previa. La slide muestra dos encuadres de la misma captura para ampliar el tipo de error y su ubicación.

## Encuadre

- PNG a resolución original, idealmente 1920×1080 o más, con zoom del navegador de 100–125% y texto legible.
- Capturar la parte útil del servicio, no todo el escritorio; conservar pestañas, etiquetas y botones que ayuden a ubicarse.
- Ocultar barra de direcciones, ID de cuenta, correo, usuario, nombre personal del perfil y datos de otras pestañas.
- Ocultar el valor completo de Function URL y cualquier ARN con el ID de cuenta; mantener visibles la etiqueta y el botón de copiar.
- No incluir credenciales, cookies, tokens, enlaces de login ni MFA; sustituir identificadores sensibles por bloques sólidos, no desenfoque débil.
- En CloudWatch incluye la hora, el evento, `team`, `request_id`, `exception_type` y `frames`. Mantén fuera los payloads y la información de otras sesiones.
- En DynamoDB, usar solo la mascota de ensayo y sus datos de ejemplo.

Para reemplazarlas, guarda las nuevas capturas en `.local/slides-captures/`, desde la raíz del repo, y revisa los datos antes de copiarlas a `slides/assets/screenshots/`.
