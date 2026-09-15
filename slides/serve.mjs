/** Serve only the built presentation on the organizer's loopback interface. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('./dist/', import.meta.url));
const port = Number(process.env.SLIDES_PORT ?? 4173);
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.md': 'text/plain', '.svg': 'image/svg+xml', '.json': 'application/json' };

/** Return a public build asset or an isolated error response. */
async function handleRequest(request, response) {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const target = resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);

    if (!target.startsWith(root.endsWith(sep) ? root : `${root}${sep}`)) {
      response.writeHead(403).end('Access denied.');
      return;
    }

    const body = await readFile(target);
    response.writeHead(200, { 'Content-Type': `${types[extname(target)] ?? 'application/octet-stream'}; charset=utf-8`, 'Cache-Control': 'no-store' });
    response.end(body);
  } catch {
    response.writeHead(404).end('File not found.');
  }
}

createServer(handleRequest).listen(port, '127.0.0.1', () => {
  console.log(`Presentation: http://127.0.0.1:${port}`);
});
