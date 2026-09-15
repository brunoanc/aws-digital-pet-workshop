/** Build a standalone presentation using only explicitly selected public files. */
import { mkdir, readFile, writeFile, cp, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
const output = `${root}dist/`;
const config = JSON.parse(await readFile(`${root}config.json`, 'utf8'));
const rawSource = await readFile(`${root}slides.md`, 'utf8');

/** Escape configuration text before inserting it into the public HTML. */
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

/** Render a verified HTTPS profile link or an explicitly inactive placeholder. */
function socialLink(value, label, placeholder) {
  if (!value) {
    return `<span class="pending-link">${placeholder}</span>`;
  }

  const url = new URL(value);

  if (url.protocol !== 'https:') {
    throw new Error('Social links must use HTTPS.');
  }

  return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer" aria-label="${label}">${escapeHtml(url.host + url.pathname)}</a>`;
}

const source = rawSource
  .replaceAll('{{eventTitle}}', escapeHtml(config.eventTitle))
  .replaceAll('{{eventDate}}', escapeHtml(config.eventDate))
  .replaceAll('{{githubLink}}', socialLink(config.githubUrl, 'Repositorio del reto en GitHub', 'github.com/USUARIO/RETO · pendiente'))
  .replaceAll('{{linkedinLink}}', socialLink(config.linkedinUrl, 'Perfil de LinkedIn del presentador', 'LinkedIn · enlace pendiente'));
const slides = source.trim().split(/\n---\n/);

/** Select a supplied background for each slide's teaching role. */
function decorateSlide(slide, index) {
  let style = 'content';

  if (index === 0) {
    style = 'title';
  } else if (/^## Follow along/m.test(slide)) {
    style = 'follow';
  } else if (/<!-- divider -->/.test(slide)) {
    style = 'divider';
  } else if (/<!-- service -->/.test(slide)) {
    style = 'service';
  }

  const extra = /<!-- compact -->/.test(slide) ? ' compact' : '';
  const diagram = /<!-- diagram -->/.test(slide) ? ' diagram' : '';
  const code = /```/.test(slide) ? ' code-slide' : '';
  const adoption = /<!-- adoption -->/.test(slide) ? ' adoption' : '';
  const closing = /<!-- closing -->/.test(slide) ? ' closing' : '';
  const capture = /<!-- capture -->/.test(slide) ? ' capture' : '';
  const centered = ['content', 'service'].includes(style) && !closing ? ' white-slide' : '';
  const background = ['title', 'divider'].includes(style) || closing
    ? `data-background-image="assets/${closing ? 'title' : style}.svg" data-background-size="contain" data-background-color="${style === 'divider' ? '#AD5CFF' : '#161d26'}"`
    : `data-background-color="${style === 'follow' ? '#fff3dc' : '#ffffff'}"`;
  const attribute = `<!-- .slide: class="${style}${extra}${diagram}${code}${adoption}${closing}${capture}${centered}" ${background} -->`;

  return `${attribute}\n\n${slide}`;
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

for (const name of ['index.html', 'theme.css', 'assets']) {
  await cp(`${root}${name}`, `${output}${name}`, { recursive: true });
}

const html = await readFile(`${root}index.html`, 'utf8');
await writeFile(`${output}index.html`, html.replace(/<title>.*?<\/title>/, `<title>${escapeHtml(config.eventTitle)}</title>`));

for (const name of ['dist']) {
  await cp(`${root}node_modules/reveal.js/${name}`, `${output}vendor/${name}`, { recursive: true });
}

await cp(`${root}node_modules/reveal.js/LICENSE`, `${output}vendor/LICENSE`);
await writeFile(`${output}slides.md`, slides.map(decorateSlide).join('\n---\n'));
console.log(`Built ${slides.length} slides in slides/dist.`);
