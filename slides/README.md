# Presentación del taller

Presentación con notas para quien imparta el taller, conceptos de AWS y Strands, ejemplos de Python y ejercicios de follow-along. Sigue el recorrido de la [guía de participantes](../participant-guide/README.md).

## Abrir

Desde `slides/`, con Node.js y npm instalados.

```bash
npm ci
npm run dev
```

Abre <http://127.0.0.1:4173>. Flechas o espacio avanzan, `Esc` muestra el índice, `F` activa pantalla completa y `S` abre las notas del presentador. Permite la ventana emergente de localhost.

Después de editar, ejecuta `npm run build` y recarga; no hay hot reload. Para cambiar el puerto, usa `SLIDES_PORT=4174 npm start` después del build.

## Editar

- [slides.md](slides.md); contenido; `---` separa slides y `Notes:` inicia las notas del presentador.
- [config.json](config.json); título, fecha y enlaces. Las URLs deben usar HTTPS; `null` muestra un placeholder sin enlace.
- [theme.css](theme.css); tamaños, colores y composición.
- [index.html](index.html); configuración de reveal.js y plugins.
- [screenshots.md](screenshots.md); capturas y datos que deben ocultarse antes de publicarlas.
- [assets/](assets/); fondos, íconos y screenshots.

El nombre del presentador y los enlaces de acceso SSO y de la app se editan en `slides.md`. Para otro grupo, actualiza también la identificación de la universidad en los fondos y reemplaza las capturas que dependan de tu entorno.

El build reconoce `<!-- service -->`, `<!-- divider -->`, `<!-- compact -->`, `<!-- diagram -->`, `<!-- adoption -->`, `<!-- closing -->` y `<!-- capture -->`. Los títulos que comienzan con `Follow along` reciben el layout de práctica. El diagrama se edita como SVG dentro del Markdown.

Los ejemplos completos están en la [guía de código](../participant-guide/agent.md).

## Deploy

`npm run build` recrea `dist/` con la presentación, assets y reveal.js. Haz el deploy de esa carpeta completa en un hosting estático. No abras `index.html` con `file://`; la presentación carga Markdown por HTTP.

Las notas también son públicas. Revisa su contenido y comprueba navegación, imágenes, enlaces y vista del presentador en Chrome y Firefox, además de la pantalla o proyector del taller.

Para generar un PDF, usa `?print-pdf` y revisa el resultado según la [guía de exportación](https://revealjs.com/pdf-export/).
