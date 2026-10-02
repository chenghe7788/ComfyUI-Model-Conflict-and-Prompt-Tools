/**
 * Regression test for the ModelImagePicker context-menu detection.
 *
 * It loads the REAL deployed model_image_picker.js (with an extra export line
 * appended to a copy) plus the real model_conflict.js, stubs fetch/object_info,
 * and checks that:
 *   - a LoRA menu whose entries include "[Artstyle]_..._[PDXL].safetensors"
 *     is still detected as a LoRA menu (this is the 2026-09-15 regression where
 *     the LoRA picker stopped opening at all),
 *   - the historic rule (stripping every leading non-alphanumeric glyph) really
 *     would have missed it,
 *   - unknown-marker prefixes ("● name") still resolve via the loose fallback,
 *   - a menu with a genuinely unknown entry is left untouched (and diagnosed).
 */

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const DEPLOY = 'C:\\ComfyUI_windows_portable\\ComfyUI\\custom_nodes\\ComfyUI_ModelImagePicker\\web\\js';
const LORA_DIR = 'C:\\ComfyUI_windows_portable\\ComfyUI\\models\\loras';

fs.mkdirSync(path.join(HERE, 'scripts'), { recursive: true });
fs.mkdirSync(path.join(HERE, 'web', 'js'), { recursive: true });

fs.writeFileSync(path.join(HERE, 'scripts', 'app.js'),
    'export const app = {\n'
    + '    registerExtension() {},\n'
    + '    canvas: { closeContextMenu() {}, setDirty() {} },\n'
    + '    graph: { _nodes: [], setDirtyCanvas() {} },\n'
    + '    ui: { settings: {} },\n'
    + '};\n');

fs.copyFileSync(path.join(DEPLOY, 'model_conflict.js'), path.join(HERE, 'web', 'js', 'model_conflict.js'));

const picker = fs.readFileSync(path.join(DEPLOY, 'model_image_picker.js'), 'utf8');
fs.writeFileSync(path.join(HERE, 'web', 'js', 'model_image_picker.js'),
    picker + '\nexport { detectModelMenu, loadModelLists, lookupModel, normalizeName, normalizeKey, modelIndex };\n');

/* ---------------- stubs ---------------- */
class StubEl {
    constructor(tag) {
        this.tagName = String(tag).toUpperCase();
        this.children = [];
        this.style = { setProperty() {} };
        this.dataset = {};
        this._classes = new Set();
        this.classList = {
            add: (...c) => c.forEach((x) => this._classes.add(x)),
            remove: (...c) => c.forEach((x) => this._classes.delete(x)),
            contains: (c) => this._classes.has(c),
            toggle: (c) => (this._classes.has(c) ? this._classes.delete(c) : this._classes.add(c)),
        };
    }
    set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
    get className() { return [...this._classes].join(' '); }
    set innerHTML(v) { this._html = String(v); }
    get innerHTML() { return this._html || ''; }
    set textContent(v) { this._text = String(v); }
    get textContent() { return this._text || ''; }
    append(...n) { this.children.push(...n); }
    appendChild(n) { this.children.push(n); return n; }
    addEventListener() {}
    removeEventListener() {}
    remove() {}
    querySelector() { return null; }
    querySelectorAll() { return []; }
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
    focus() {}
    closest() { return null; }
}
globalThis.document = {
    createElement: (t) => new StubEl(t),
    createTextNode: (t) => ({ textContent: String(t) }),
    head: { appendChild() {} },
    body: { appendChild() {}, append() {} },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    documentElement: new StubEl('html'),
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });

const walk = (d, base = '') => {
    const out = [];
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const rel = base ? base + '\\' + e.name : e.name;
        if (e.isDirectory()) out.push(...walk(path.join(d, e.name), rel));
        else if (/\.(safetensors|pt|ckpt|sft)$/i.test(e.name)) out.push(rel);
    }
    return out;
};
const LORAS = walk(LORA_DIR);
const CHECKPOINTS = ['MatureRitual_v03EXP.safetensors', 'prefectPonyXL_v6.safetensors', 'sd3_medium.safetensors'];

const seen = [];
globalThis.fetch = async (u) => {
    const s = String(u);
    seen.push(s);
    const json = (obj) => ({ ok: true, status: 200, json: async () => obj, text: async () => JSON.stringify(obj) });
    if (s.includes('/modelconflict/index')) {
        return json({ labels: {}, roles: {}, kinds: { loras: LORAS, checkpoints: CHECKPOINTS } });
    }
    if (s.includes('/modelpreview/debug')) return json({ ok: true });
    return json({});
};

/* ---------------- harness ---------------- */
let fail = 0;
const expect = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) fail++;
    console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label.padEnd(52)} ${ok ? JSON.stringify(got) : 'got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)}`);
};

const M = await import('./web/js/model_image_picker.js');
await M.loadModelLists();
console.log('indexed names:', M.modelIndex.size, '| disk LoRAs:', LORAS.length);

const artstyle = LORAS.find((n) => n.startsWith('[Artstyle]'));
console.log('regression model:', JSON.stringify(artstyle));

console.log('\n[regression: LoRA menu containing a "[" model]');
const loraMenu = [
    { content: '\u2713 ' + artstyle, callback() {} },
    { content: 'None', callback() {} },
    ...LORAS.filter((n) => n !== artstyle).map((n) => ({ content: n, callback() {} })),
];
const det = M.detectModelMenu(loraMenu, {}, undefined);
expect('menu detected as loras', det && det.kind, 'loras');
expect('all LoRAs listed (None dropped)', det && det.names.length, LORAS.length);
expect('current entry = the "[" model', det && det.currentName, M.normalizeKey(artstyle));

console.log('\n[proof the old rule failed]');
const oldNormalize = (s) => String(s).replace(/\\/g, '/').toLowerCase()
    .replace(/^[^0-9A-Za-z\u4e00-\u9fff]+/, '');
expect('old strip mangles the name', oldNormalize(artstyle) !== M.normalizeKey(artstyle), true);
expect('new normalize keeps it', M.normalizeName(artstyle), M.normalizeKey(artstyle));
expect('plain names unchanged', M.normalizeName('\u7070\u539f\u54c0\\Miyano_Shiho_IL_V2.safetensors'),
    M.normalizeKey('\u7070\u539f\u54c0\\Miyano_Shiho_IL_V2.safetensors'));

console.log('\n[other menu shapes]');
const d2 = M.detectModelMenu(CHECKPOINTS.map((n) => ({ content: n, callback() {} })), {}, undefined);
expect('checkpoint menu detected', d2 && d2.kind, 'checkpoints');

const marked = LORAS.slice(0, 5).map((n, i) => ({ content: i === 0 ? '\u25cf ' + n : n, callback() {} }));
const d3 = M.detectModelMenu(marked, {}, undefined);
expect('unknown marker still resolves (loose fallback)', d3 && d3.kind, 'loras');

const withUnknown = [
    { content: 'no-such-model.safetensors', callback() {} },
    ...LORAS.map((n) => ({ content: n, callback() {} })),
];
const d4 = M.detectModelMenu(withUnknown, {}, undefined);
expect('one unknown entry no longer vetoes', d4 && d4.kind, 'loras');
expect('...the unknown entry is simply not offered', d4 && d4.names.length, LORAS.length);
expect('...and is reported for diagnosis', seen.some((u) => u.includes('/modelpreview/debug')), true);

const mostlyUnknown = [
    ...LORAS.slice(0, 3).map((n) => ({ content: n, callback() {} })),
    ...Array.from({ length: 12 }, (_, i) => ({ content: 'menu-command-' + i, callback() {} })),
];
expect('a mostly-unknown menu is still left untouched',
    M.detectModelMenu(mostlyUnknown, {}, undefined), null);

const withSub = [
    { content: 'group', has_submenu: true },
    ...LORAS.slice(0, 4).map((n) => ({ content: n, callback() {} })),
];
expect('submenu vetoes the menu', M.detectModelMenu(withSub, {}, undefined), null);
expect('empty menu ignored', M.detectModelMenu([], {}, undefined), null);
expect('separator (null) vetoes the menu',
    M.detectModelMenu([null, ...LORAS.slice(0, 4).map((n) => ({ content: n }))], {}, undefined), null);

console.log('\nFAILURES:', fail);
process.exitCode = fail ? 1 : 0;
