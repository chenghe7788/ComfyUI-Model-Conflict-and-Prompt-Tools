/**
 * Stub of ComfyUI's ../../scripts/app.js for the headless SmartCLIP test.
 * Also stubs the DOM bits the dialog touches, because node has no document.
 *
 * The stub deliberately mirrors the frontend actually shipped with this install
 * (comfyui-frontend-package 1.41.21):
 *   - LiteGraph keeps links in `graph._links` (a Map); `graph.links` is declared
 *     but never assigned, so `graph.links[id]` is undefined.
 *   - `graph.getNodeById(id)` exists.
 */

export const registry = { extensions: [] };

export const app = {
    graph: globalThis.__FAKE_APP__?.graph || { _nodes: [], _links: new Map() },
    registerExtension(ext) {
        registry.extensions.push(ext);
        return ext;
    },
};

/* ------------------------------------------------------------------ *
 * Minimal DOM
 * ------------------------------------------------------------------ */

const innerHtmlWrites = [];
globalThis.__INNER_HTML_WRITES__ = innerHtmlWrites;

class StubElement {
    constructor(tag) {
        this.tagName = String(tag).toUpperCase();
        this.children = [];
        this.parentNode = null;
        // Mirrors CSSStyleDeclaration just enough: the picker sets --sc-emb-cell
        // through setProperty, and tests read the value back.
        this.style = {
            setProperty(key, value) { this[key] = value; },
            getPropertyValue(key) { return this[key] || ""; },
            removeProperty(key) { delete this[key]; },
        };
        this.dataset = {};
        this._text = "";
        this._classes = new Set();
        this._listeners = {};
        this.value = undefined;
        const self = this;
        this.classList = {
            add: (...c) => c.forEach((x) => self._classes.add(x)),
            remove: (...c) => c.forEach((x) => self._classes.delete(x)),
            toggle: (c, on) => (on ? self._classes.add(c) : self._classes.delete(c)),
            contains: (c) => self._classes.has(c),
        };
    }
    set className(v) {
        this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
    }
    get className() {
        return [...this._classes].join(" ");
    }
    set textContent(v) {
        this._text = String(v);
        this.children = [];
    }
    get textContent() {
        return this._text + this.children.map((c) => c.textContent || "").join("");
    }
    set innerHTML(v) {
        innerHtmlWrites.push(String(v));
        this._text = String(v);
    }
    get innerHTML() {
        return this._text;
    }
    append(...nodes) {
        for (const n of nodes) {
            const child = typeof n === "string" ? { textContent: n, children: [] } : n;
            if (child.parentNode !== undefined) child.parentNode = this;
            this.children.push(child);
        }
    }
    appendChild(n) {
        this.append(n);
        return n;
    }
    remove() {
        if (this.parentNode) {
            const at = this.parentNode.children.indexOf(this);
            if (at >= 0) this.parentNode.children.splice(at, 1);
        }
        this.parentNode = null;
    }
    addEventListener(type, fn) {
        (this._listeners[type] = this._listeners[type] || []).push(fn);
    }
    removeEventListener(type, fn) {
        const list = this._listeners[type] || [];
        const at = list.indexOf(fn);
        if (at >= 0) list.splice(at, 1);
    }
    dispatchEvent(event) {
        for (const fn of this._listeners[event?.type] || []) fn(event);
        return true;
    }
    /** test helper: fire a click (with the DOM methods real handlers call) */
    click() {
        const event = { type: "click", target: this, preventDefault() {}, stopPropagation() {} };
        for (const fn of this._listeners.click || []) fn(event);
    }
    /** test helper: fire a right click on this element */
    contextMenu(pageX = 10, pageY = 10) {
        const event = { type: "contextmenu", target: this, pageX, pageY, preventDefault() {}, stopPropagation() {} };
        for (const fn of this._listeners.contextmenu || []) fn(event);
    }
    /** test helper: every descendant matching a class */
    findAll(className) {
        const out = [];
        const walk = (node) => {
            for (const child of node.children || []) {
                if (child._classes?.has(className)) out.push(child);
                walk(child);
            }
        };
        walk(this);
        return out;
    }
    querySelectorAll(selector) {
        return this.findAll(String(selector).replace(/^\./, ""));
    }
    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }
    focus() {}
}

/** Every document-level listener, so a test can fire one by hand. */
const docListeners = {};

globalThis.document = {
    createElement: (tag) => new StubElement(tag),
    createTextNode: (text) => {
        const node = new StubElement("#text");
        node.textContent = String(text);
        return node;
    },
    head: new StubElement("head"),
    body: new StubElement("body"),
    addEventListener(type, fn) {
        (docListeners[type] = docListeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
        const list = docListeners[type] || [];
        const at = list.indexOf(fn);
        if (at >= 0) list.splice(at, 1);
    },
    /** test helper: fire a document-level listener (capture phase included) */
    dispatch(type, event) {
        for (const fn of docListeners[type] || []) fn(event);
    },
};

/* The completion popup positions itself against the viewport. */
globalThis.window = {
    innerWidth: 1280,
    innerHeight: 800,
    addEventListener() {},
    removeEventListener() {},
};

globalThis.Event = class Event {
    constructor(type, opts) {
        this.type = type;
        Object.assign(this, opts || {});
    }
};

export { StubElement };
