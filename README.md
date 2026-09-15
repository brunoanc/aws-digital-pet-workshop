# Build Your First AI Agent on AWS

Workshop diseñado para un AWS Student Builder Group; un agente construido con Strands y Amazon Bedrock consulta y cuida una mascota almacenada en DynamoDB. El agente y las acciones se ejecutan en AWS Lambda.

## Documentación

- [Guía de participantes](participant-guide/README.md); recorrido desde la consola de AWS, sin instalaciones locales.
- [Guía del organizador](organizer-guide/README.md); configuración, deploy, pruebas, recuperación y cierre.
- [Presentación](slides/README.md); fuente, build y deploy.
- [Configuración y operación](docs/README.md); instrucciones para montar y mantener el lab.

## Estructura del repo

| Carpeta | Contenido |
|---|---|
| `agent_lambda/` | Starter del agente, handler, y tools |
| `lambda/` | Reglas, persistencia y acciones de la mascota |
| `app/` | Web app compartida |
| `checkpoints/` | Soluciones por etapa |
| `infra/` | Stacks Terraform |
| `hosting/` | Plantillas de Caddy y servicios del servidor |
| `config/` | Entradas del entorno y los equipos, backends y ejemplos de carga |
| `fixtures/` | Datos iniciales de mascotas |
| `scripts/` | Configuración, deploy, diagnóstico y recuperación |
| `tests/` | Pruebas locales y de capacidad |
| `participant-guide/`, `organizer-guide/`, `docs/` | Documentación |
| `slides/` | Presentación y assets |
| `.streamlit/` | Estilos de la web app |

## Licencia

Copyright (C) 2026 Bruno Ancona.

El código original de este proyecto se distribuye bajo [GNU AGPL versión 3](LICENSE). Los logos, marcas y assets de terceros conservan sus propias licencias y condiciones.
