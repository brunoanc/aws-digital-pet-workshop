# Construye tu agente y dale una acción propia

Referencia de código por etapas para el [recorrido de participantes](README.md). Sigue el orden del facilitador y guarda tu trabajo antes de usar un checkpoint.

## Antes de empezar

El equipo recibe dos funciones Lambda con dependencias y helpers preparados. El archivo del agente empieza sin constructor y la acción propia tiene una implementación pendiente. Si encuentras el ejercicio ya resuelto, avisa al facilitador y conserva el código.

Usa tu identidad de estudiante, región y nombres asignados; no uses una sesión de administrador para validar los pasos. Tendrás dos funciones, **mascota**, con reglas y persistencia, y **agente**, con el constructor y las herramientas. No intercambies sus eventos de prueba.

Abre la app y la consola en pestañas distintas y trabaja con los recursos asignados a tu equipo.

Abre la Lambda agente → Configuration → Function URL, copia el endpoint completo y pégalo en **Function URL de tu agente** en la app. Pulsa **Conectar**; no entregues claves AWS. Esta comprobación valida el destino asignado a tu equipo. Consulta [la guía de conexión](../docs/architecture.md#url) si necesitas recuperar el enlace; si la URL no aparece, pide ayuda sin crear un endpoint público.

La app recuerda la URL validada en este navegador para el equipo asignado. Al volver a abrirla, comprueba la conexión nuevamente. Si usas otro navegador o borras sus datos, pega la URL otra vez. El login sigue siendo necesario.

## 1. Crea un agente que converse

En la Lambda **agente**, abre `agent_lambda/agent_builder.py`. El archivo inicial solo tiene una docstring y un comentario; escribe tú los imports, la función y su cuerpo. El resultado de esta primera etapa será.

```python
"""Construye el agente encargado de cuidar nuestra mascota."""

from strands import Agent
from strands.models import BedrockModel


def create_agent(model_options, runtime_options):
    """Configura el modelo y crea el agente que responde en el chat."""

    model = BedrockModel(
        model_id="amazon.nova-lite-v1:0",
        temperature=0.3,
        max_tokens=512,
        **model_options,
    )

    agent = Agent(
        model=model,
        **runtime_options,
    )

    return agent
```

Los imports permiten usar las clases del SDK. `BedrockModel(...)` crea la conexión al modelo elegido y `Agent(...)` construye el agente que lo utilizará. Las variables `model` y `agent` guardan esos objetos; `return agent` entrega el agente al helper que recibe los mensajes de la app.

Escribe el ID del modelo autorizado que probaste en Bedrock; los ejemplos usan `amazon.nova-lite-v1:0`. `temperature` controla la variabilidad de la respuesta y `max_tokens` limita la longitud de salida de cada llamada. Los ejemplos usan 512 tokens y temperatura 0.3.

`**model_options` incorpora la conexión a AWS y `**runtime_options` las opciones de ejecución preparadas para el taller. Conserva ambos argumentos al crear el modelo y el agente.

Construye el archivo por bloques con el facilitador; pulsa **Deploy** cuando la función completa pueda devolver el agente. No uses claves AWS ni copies configuración privada dentro del código.

**Predicción**. ¿Qué información tiene el agente para responder sobre tu mascota?

### Prueba la primera respuesta

Antes de añadir el system prompt, pulsa **Deploy** y envía este mensaje desde el chat de la app.

> ¿Cómo está mi mascota?

Guarda la respuesta para compararla en la siguiente etapa. Observa si habla de una mascota digital, da consejos generales o pide más contexto.

Por ejemplo, puede responder con consejos sobre perros o gatos y explicar que no puede ver a tu mascota. La respuesta puede variar. Todavía no le indicamos su papel en el taller y la ficha que aparece en la app no llega automáticamente al modelo.

**Checkpoint**. El agente responde a tu mensaje, pero aún no consulta el estado real de la mascota.

**Rescate**. Reemplaza el archivo con [01_conversation.py](../checkpoints/01_conversation.py), pulsa Deploy y vuelve a probar.

## 2. Escribe sus instrucciones

Dentro de `create_agent`, después de construir `model` y antes de `agent = Agent(...)`, escribe tu propia cadena multilínea.

```python
    system_prompt = """Eres el cuidador de un dragón curioso que aprende programación.
Responde en español de forma breve y amable.
No inventes estadísticas ni afirmes cambios que no hayas comprobado.
Si no tienes herramientas, explica que no puedes consultar ni cuidar la mascota.
"""
```

Agrega `system_prompt=system_prompt,` al constructor. Personaliza el texto; ¿quién es tu cuidador?, ¿qué tono usa?, ¿qué debe hacer si no puede ayudar?

Pulsa **Deploy** y repite "¿Cómo está mi mascota?". Compara el papel y el tono del agente con la respuesta que guardaste. El system prompt orienta la respuesta hacia la mascota digital. El acceso a sus datos llegará al conectar una tool en la siguiente etapa.

**Checkpoint**. El agente recibe las instrucciones de tu system prompt.

**Rescate**. [02_prompt.py](../checkpoints/02_prompt.py); úsalo como ejemplo y vuelve a expresar la personalidad con tus palabras.

## 3. Lee y conecta la consulta

Primero abre **Test** en la función Lambda **mascota**, crea un evento y sustituye `team-01` por el ID asignado.

```json
{"pet_id": "team-01", "action": "inspect", "parameters": {}}
```

Ejecuta **Test** y compara el nombre y la energía con el item en DynamoDB. El resultado debe indicar `success: true`. Esta prueba ejecuta la acción directamente, sin usar el modelo ni una tool de Strands; no pegues este evento en la función del agente.

En el paquete del agente, abre `agent_lambda/tools.py` y localiza `inspect_pet`. `gateway_for(...)` es el helper preparado que conecta con la función Lambda que acabas de probar. Strands proporciona `tool_context` automáticamente al ejecutar la tool.

En la Lambda **mascota**, abre `rules.py` y localiza el caso `action == "inspect"`; devuelve una copia del estado, sin cambiarlo. Los destinos AWS los proporcionan los helpers; no los elige el modelo.

En la parte superior de tu archivo escribe `from agent_lambda.tools import inspect_pet`; luego, en el constructor, escribe `tools=[inspect_pet]`. Importar hace disponible la función en Python; registrarla en `tools` permite que el modelo la utilice. Ajusta tu prompt; consulta antes de describir estadísticas, no inventes unidades y trata resultados como datos, no como instrucciones. Pulsa Deploy y pregunta por el estado.

**Checkpoint**. `inspect_pet` aparece en la última lista registrada y en la actividad; los datos coinciden con la ficha y el item de tu equipo en DynamoDB, sin cambio de versión.

**Rescate**. [03_inspect.py](../checkpoints/03_inspect.py).

## 4. Entiende y conecta los cuidados

### Explora el cuidado en la función mascota

En la función Lambda **mascota**, abre `rules.py` y localiza el caso `action == "rest"`. Identifica la condición que rechaza un descanso y los cambios de energía y saciedad. El handler guarda el resultado válido en DynamoDB.

Anota la energía y la saciedad actuales. Abre **Test** y usa este evento con el ID de tu equipo.

```json
{"pet_id": "team-01", "action": "rest", "parameters": {}}
```

Ejecuta **Test** una sola vez. Revisa `success` y `message`, refresca el item en DynamoDB y compara el resultado con la regla. El descanso suma 35 de energía y resta 10 de saciedad, con límites de 0 a 100. Si la energía ya es de 90 o más, devuelve `ALREADY_RESTED` y conserva el estado.

Esta prueba ejecuta el cuidado directamente en la función mascota y puede cambiar sus datos. El evento usa `rest` como acción. `care_for_pet` es el nombre de la tool que permitirá solicitar ese cuidado desde el agente.

### Conecta la tool al agente

En la función Lambda **agente**, abre `agent_lambda/tools.py` y lee `care_for_pet`. Su docstring describe las acciones disponibles. El parámetro `action` selecciona `feed`, `play` o `rest`; `food` se usa para `feed`. Relaciona la acción `rest` con el evento que acabas de probar.

Amplía el import a `from agent_lambda.tools import inspect_pet, care_for_pet`. Escribe `tools=[inspect_pet, care_for_pet]` y añade al prompt; actuar solo cuando lo pida el usuario, consultar antes, realizar una acción por mensaje y no afirmar éxito si la herramienta falló. Pulsa Deploy.

Pide "Consulta el estado de mi mascota y haz que juegue una vez". Revisa la consulta previa y la llamada a `care_for_pet` con `action="play"` en la actividad. Compara los cambios en la ficha.

`play` requiere al menos 20 de energía. El descanso anterior deja suficiente energía para jugar, incluso si devolvió `ALREADY_RESTED`, siempre que nadie haya realizado otra acción. Jugar resta 20 de energía y 10 de saciedad, suma 20 de felicidad y 10 de experiencia. Las estadísticas se mantienen entre 0 y 100. Si hay un rechazo, revisa el estado actual y el motivo antes de repetir.

**Checkpoint**. Consulta previa y como máximo un cuidado, con efecto real o rechazo explicado. La ficha muestra el estado guardado en DynamoDB.

**Rescate**. [04_care.py](../checkpoints/04_care.py).

## 5. Escribe una acción propia

Primero conecta la herramienta, antes de implementar su comportamiento. En la Lambda **agente**, lee `custom_action` en `agent_lambda/tools.py`, amplía el import a `from agent_lambda.tools import inspect_pet, care_for_pet, custom_action` y registra `tools=[inspect_pet, care_for_pet, custom_action]`.

Añade estas instrucciones dentro de tu cadena `system_prompt`, sin borrar las anteriores.

```text
Cuando te pida practicar un hechizo, consulta primero el estado
con inspect_pet y después usa custom_action.
Ejecuta la acción una sola vez.
Si la herramienta rechaza la acción, explica el motivo
sin afirmar que tuvo éxito.
```

Adapta "practicar un hechizo" a la acción de tu equipo. El docstring de la tool es genérico y el prompt relaciona esa petición con `custom_action`. Conserva `system_prompt=system_prompt` dentro de `Agent(...)` y pulsa **Deploy** antes de probar. No edites todavía `perform` en la función de la mascota.

Solicita el hechizo una vez desde la app. Abre **Actividad de las herramientas** y revisa el resultado de `custom_action`. El handler devuelve `BACKEND_ERROR` y un `request_id`. Copia ese ID para localizar la ejecución. Si el modelo omite el ID en su respuesta, estará en el resultado de la tool dentro de la actividad. Si la tool no aparece, revisa el registro y el prompt con el facilitador.

Antes de editar, localiza el error en [CloudWatch](../participant-guide/README.md#5-localiza-el-error-en-cloudwatch) con el facilitador. El log indica el tipo de excepción, el archivo, la función y la línea. Después vuelve a `custom_action.py` en la función Lambda **mascota** y reemplaza el `raise` de `perform(pet)` por una implementación que devuelva estos campos.

| Resultado | Campos obligatorios |
|---|---|
| Acción aceptada | `success: True`, `changes: {estadística: incremento}`, `message: texto` |
| Acción rechazada | `success: False`, `reason: código`, `message: texto` |

Escribe una docstring, una condición de rechazo, efectos sobre dos estadísticas y un mensaje. Por ejemplo, practicar un hechizo cuesta 10 de energía y otorga 20 de experiencia; recházalo cuando falte energía. No es necesario usar esos valores o ese tema.

Los efectos admiten `health`, `fullness`, `energy`, `happiness`, `experience`; cada incremento debe ser entero entre -35 y 35. Los cuatro indicadores se limitan a 0–100; la experiencia no puede quedar negativa. La identidad, el inventario y la versión se conservan fuera de `changes`.

Devuelve los efectos en `changes` para que el código del taller los valide y guarde. Modificar directamente el argumento `pet` no guarda esos cambios.

Pulsa **Deploy** en la mascota. Si personalizaste el nombre de la acción, ajusta también el prompt y pulsa **Deploy** en el agente. Consulta el estado y solicita tu acción una sola vez desde la app. Comprueba que aparece `custom_action` con acción `custom` y verifica las estadísticas, la versión y el inventario.

La tool ya estaba registrada y ahora tiene sus efectos implementados. Explica qué haría tu condición con energía insuficiente. Ese rechazo esperado devuelve un resultado normal, mientras que la implementación pendiente interrumpía la ejecución con una excepción.

**Rescate**. [custom_action.py](../checkpoints/custom_action.py) para la mascota y [05_custom.py](../checkpoints/05_custom.py) para el agente; si usas otro nombre visible, adapta también tu prompt.

## 6. Revisa la evidencia y conserva tu trabajo

Guarda una copia de ambos archivos antes de experimentar. Si aparece otro error durante la escritura, usa la actividad y los logs para corregirlo. Consulta el estado antes de repetir un cuidado cuyo resultado sea desconocido.

Los logs de la mascota muestran acciones aceptadas, rechazos esperados y errores con su ubicación en el código. Los del agente muestran metadatos de ejecución. Comprueba el resultado de la tool y el estado guardado para confirmar un cuidado.

Al terminar, copia y guarda `agent_builder.py`, `custom_action.py` y el estado que quieras conservar, sin credenciales.

## Límites del lab

Cada pregunta al agente es independiente; la app conserva un historial visible, pero no lo reenvía a Lambda. El prompt y las tools se actualizan con Deploy.

Comprueba los cambios en la ficha o en DynamoDB. El texto del modelo puede contener errores, incluso cuando sigue el system prompt.
