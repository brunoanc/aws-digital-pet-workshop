# Ayuda durante el taller

[Volver al recorrido](README.md)

| Lo que ves | Qué hacer |
|---|---|
| No aparece tu cuenta o permiso | Comprueba tu usuario y pide ayuda; no crees usuarios ni permisos |
| El acceso al taller no está habilitado | Pide al organizador que revise la ventana; recargar no la renueva |
| Tu cuenta no tiene equipo asignado | Pide que revisen la asignación; no uses la identidad de otra persona |
| No se pudo conectar | Comprueba la URL de la Lambda agente, la sesión y el equipo |
| Tu equipo ya está esperando una respuesta | Espera a la otra pestaña o integrante; no dupliques el mensaje |
| Espera unos segundos | Respeta el intervalo antes de enviar otro mensaje |
| Tu equipo alcanzó el límite de mensajes | Avisa al organizador; cambiar de pestaña no restablece la cuota |
| El modelo no conoce la mascota | Revisa import, `tools`, prompt y Deploy; la ficha no se envía al modelo |
| `BACKEND_ERROR` | Copia el `request_id` de la actividad y busca el error en los logs de la mascota. Revisa el estado antes de reintentar |
| `NotImplementedError` en los logs | Abre el archivo y la línea indicados. En el starter falta completar `perform` |
| `NEEDS_REST` u otro rechazo de cuidado | Lee la regla y el estado; no lo confundas con un fallo de AWS |
| No se pudo confirmar el resultado | Consulta la ficha y pide revisar logs antes de repetir un cuidado |
| No aparecen eventos en CloudWatch | Comprueba grupo, región y horario, espera y actualiza |
| Error de sintaxis | Revisa indentación, comas y comillas; guarda tu trabajo antes de usar un checkpoint |

Si necesitas ayuda, indica equipo, paso, hora y mensaje de error; no compartas contraseña, cookies ni credenciales. Una respuesta del modelo no prueba un cambio, revisa la actividad y la ficha.
