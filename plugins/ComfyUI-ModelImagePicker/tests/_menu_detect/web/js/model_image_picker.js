/**
 * ComfyUI Model Image Picker  -  frontend extension
 * =================================================
 * Adds a button on CheckpointLoaderSimple and LoraLoader nodes. Clicking it opens
 * a centered MODAL dialog that shows every available model as a thumbnail, so you
 * can pick a model by its picture instead of its filename.
 *
 * Preview images come from the sidecar .png next to each model file (the same
 * ones SD WebUI uses) and are served by model_preview_api.py.
 *
 * Why a modal instead of a floating panel anchored to the node:
 *   The graph canvas is zoomed/panned by a CSS transform. A fixed-position panel
 *   whose coordinates are derived from the canvas transform shifts and appears to
 *   grow every time the user scrolls (wheel = canvas zoom). A centered modal does
 *   not depend on the canvas transform at all, so canvas zoom/pan cannot affect
 *   it. Wheel events inside the modal are stopped from reaching the canvas, and
 *   the grid scrolls natively instead.
 *
 * Interaction:
 *   - single click a card  -> select (modal stays open so you can compare)
 *   - double click a card  -> select and close
 *   - Esc or click outside -> close
 *   - "Size" slider        -> change the thumbnail size
 */

import { app } from "../../scripts/app.js";
import {
    NODE_FIELDS,
    applyCardState,
    buildLegend,
    indexKinds,
    statusFor,
} from "./model_conflict.js";

const EXT_NAME = "ModelImagePicker";
const API_LIST = "/modelpreview/list";
const API_IMG = "/modelpreview/img";

/**
 * Node types this picker attaches to, and which model folder each one uses.
 *
 * The table itself lives in model_conflict.js, which also uses it to read the
 * workflow's models, so both features always agree on the supported kinds.
 * (checkpoints / LoRAs / VAEs / ControlNet / UNET / text encoders / upscalers /
 *  SAM / detector models)
 */
const NODE_KIND = {};
const NODE_FIELD = {};
for (const [nodeType, [kind, field]] of Object.entries(NODE_FIELDS)) {
    NODE_KIND[nodeType] = kind;
    NODE_FIELD[nodeType] = field;
}

const LABEL = {
    checkpoints: "\u5927\u6a21\u578b",   // 大模型
    loras: "LoRA",
    vae: "VAE",
    embeddings: "\u8bcd\u5d4c\u5165",     // 词嵌入
    controlnet: "ControlNet",
    diffusion_models: "UNET",
    text_encoders: "\u6587\u672c\u7f16\u7801\u5668",   // 文本编码器
    upscale_models: "\u653e\u5927\u6a21\u578b",         // 放大模型
    sams: "SAM",
    ultralytics: "\u68c0\u6d4b\u6a21\u578b",            // 检测模型
};

const MSG = {
    empty: "\u6ca1\u6709\u627e\u5230\u6a21\u578b",             // 没有找到模型
    emptyHint: "\u8bd5\u8bd5\u6e05\u7a7a\u641c\u7d22\u5173\u952e\u5b57",  // 试试清空搜索关键字
    noPreview: "\u65e0\u9884\u89c8\u56fe",                     // 无预览图
    search: "\u641c\u7d22\u6a21\u578b\u540d\u2026",            // 搜索模型名…
    current: "\u5f53\u524d",                                   // 当前
    currentBadge: "\u5f53\u524d\u4f7f\u7528",                  // 当前使用
    none: "\u672a\u9009\u62e9",                                // 未选择
    size: "\u56fe\u7247\u5927\u5c0f",                          // 图片大小
    close: "\u5173\u95ed",                                     // 关闭
    total: "\u5171",                                           // 共
    withImg: "\u6709\u56fe",                                   // 有图
    shown: "\u663e\u793a",                                     // 显示
    hint: "\u5355\u51fb\u9009\u4e2d \u00b7 \u53cc\u51fb\u9009\u4e2d\u5e76\u5173\u95ed \u00b7 Esc \u5173\u95ed",
    // list request failed (as opposed to "this folder is really empty")
    loadFailed: "\u52a0\u8f7d\u5931\u8d25",                       // 加载失败
    loadFailedHint: "\u6a21\u578b\u5217\u8868\u63a5\u53e3\u6ca1\u6709\u54cd\u5e94\uff0c\u8bf7\u91cd\u542f ComfyUI \u540e\u518d\u8bd5",
    retry: "\u91cd\u8bd5",                                      // 重试
    emptyFolder: "\u8be5\u7c7b\u578b\u4e0b\u6ca1\u6709\u6a21\u578b\u6587\u4ef6",   // 该类型下没有模型文件
};

/** Default / min / max grid column width in px (the "Size" slider). */
const CELL_DEFAULT = 120;
const CELL_MIN = 72;
const CELL_MAX = 300;
const CELL_STEP = 8;
const CELL_STORE_KEY = "mip.cellWidth";

/* ------------------------------------------------------------------ *
 * Universal interception state
 *
 * The goal is that model pickers belonging to ANY custom node open this modal,
 * not just the nodes we attach a button to. Most extensions build their model
 * list through LiteGraph's context menu, so that constructor is wrapped.
 * ------------------------------------------------------------------ */

/** Every modal currently on screen, so we never stack two of them. */
const openModals = new Set();

/**
 * True between "a model menu was detected" and "our modal was created".
 *
 * The takeover awaits the model index, and during that window no modal exists
 * yet - so `openModals.size === 0` is not enough to tell a second click (or a
 * double click) that a picker is already on its way.
 */
let takeoverPending = false;

/** Drop modals whose DOM was removed without going through destroy(). */
function pruneOpenModals() {
    for (const m of openModals) {
        if (m._destroyed || !m.backdrop?.isConnected) openModals.delete(m);
    }
}

/**
 * Remove any NATIVE menu that is still on screen.
 *
 * Our modal replaces the ContextMenu a model combo opens, but the real menu is
 * constructed first (so behaviour stays intact when we bail out) and a second
 * one can be produced by the click that opened us.  Anything left behind sits
 * *behind* the modal, so dismissing the modal appears to need a second close.
 */
function closeNativeMenus() {
    try {
        app.canvas?.closeContextMenu?.();
    } catch { /* ignore */ }
    try {
        globalThis.LiteGraph?.ContextMenu?.activeMenu?.close?.();
    } catch { /* ignore */ }
    try {
        for (const root of document.querySelectorAll?.(".litecontextmenu") || []) {
            root.remove?.();
        }
    } catch { /* ignore */ }
    try {
        for (const root of document.querySelectorAll?.(".combo-menu, [data-testid='combo-menu']") || []) {
            root.remove?.();
        }
    } catch { /* ignore */ }
}

/**
 * name(lowercased) -> the kinds that provide it. A name may exist both as a
 * checkpoint and as a lora, in which case both kinds are kept and the first is
 * used (checkpoints win, they are the more likely intent).
 */
const modelIndex = new Map();

let modelListsLoaded = false;
let modelListsPromise = null;

/* ------------------------------------------------------------------ *
 * Small DOM helper
 * ------------------------------------------------------------------ */

function el(tag, style, text) {
    const node = document.createElement(tag);
    if (style) Object.assign(node.style, style);
    if (text != null) node.textContent = text;
    return node;
}

/* ------------------------------------------------------------------ *
 * Styles (injected once)
 * ------------------------------------------------------------------ */

const CSS = `
.mip-backdrop {
    position: fixed;
    inset: 0;
    z-index: 12000;
    background: rgba(0,0,0,.62);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    /* The panel must never react to the graph transform. */
    transform: none !important;
    font: 12px/1.4 system-ui, "Microsoft YaHei", sans-serif;
}
.mip-modal {
    background: #17171c;
    color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.16);
    border-radius: 12px;
    box-shadow: 0 20px 60px rgba(0,0,0,.7);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    /* Sized against the viewport, independent of any canvas zoom. */
    width: min(1180px, 94vw);
    height: min(86vh, 900px);
}
.mip-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: #1e1e24;
    border-bottom: 1px solid rgba(255,255,255,.09);
    flex: 0 0 auto;
    flex-wrap: wrap;
}
.mip-title { font-size: 15px; font-weight: 700; color: #4a9eff; white-space: nowrap; }
.mip-count { color: #8a8a95; white-space: nowrap; }
.mip-spacer { flex: 1 1 auto; }
.mip-search {
    flex: 1 1 200px;
    min-width: 140px;
    background: #101014;
    border: 1px solid rgba(255,255,255,.18);
    border-radius: 7px;
    color: #e8e8ea;
    padding: 6px 10px;
    font: inherit;
    outline: none;
}
.mip-search:focus { border-color: #4a9eff; }
.mip-btn {
    background: #26262e;
    border: 1px solid rgba(255,255,255,.16);
    border-radius: 7px;
    color: #d8d8dd;
    cursor: pointer;
    padding: 5px 12px;
    font: inherit;
}
.mip-btn:hover { background: #33333d; color: #fff; }
.mip-close { font-size: 14px; line-height: 1; padding: 5px 10px; }
.mip-size {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #8a8a95;
    white-space: nowrap;
}
.mip-size input { width: 130px; accent-color: #4a9eff; }
.mip-current {
    flex: 0 0 auto;
    padding: 8px 16px;
    background: #141419;
    border-bottom: 1px solid rgba(255,255,255,.06);
    color: #9a9aa6;
    word-break: break-all;
}
.mip-current b { color: #5bc27e; font-weight: 600; }
.mip-body {
    flex: 1 1 auto;
    overflow-y: auto;
    overscroll-behavior: contain;   /* do not chain scrolling to the page */
    padding: 14px;
}
.mip-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--mip-cell, 120px), 1fr));
    gap: 10px;
}
.mip-card {
    background: #202027;
    border: 1px solid rgba(255,255,255,.09);
    border-radius: 9px;
    cursor: pointer;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    position: relative;
}
.mip-card:hover { border-color: #4a9eff; background: #262630; }
.mip-card.mip-sel {
    border-color: #5bc27e;
    box-shadow: 0 0 0 2px #5bc27e inset;
    background: #24322a;
}
/* "in use" badge shown on the active model's card */
.mip-badge {
    position: absolute;
    top: 5px;
    left: 5px;
    z-index: 2;
    background: #5bc27e;
    color: #08210f;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    box-shadow: 0 1px 4px rgba(0,0,0,.5);
}
/* brief flash so the eye lands on the active card when the picker opens */
@keyframes mip-pulse-kf {
    0%   { box-shadow: 0 0 0 2px #5bc27e inset, 0 0 0 0 rgba(91,194,126,.75); }
    70%  { box-shadow: 0 0 0 2px #5bc27e inset, 0 0 0 12px rgba(91,194,126,0); }
    100% { box-shadow: 0 0 0 2px #5bc27e inset, 0 0 0 0 rgba(91,194,126,0); }
}
.mip-card.mip-pulse { animation: mip-pulse-kf 1.3s ease-out 2; }
.mip-thumb {
    width: 100%;
    aspect-ratio: 1 / 1;
    /* SD WebUI previews are often very wide comparison strips (e.g. 5824x1381),
       so "contain" keeps the whole picture visible instead of cropping it. */
    object-fit: contain;
    display: block;
    background: #0e0e12;
}
.mip-thumb-empty {
    width: 100%;
    aspect-ratio: 1 / 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #5a5a66;
    background: #0e0e12;
    font-size: 11px;
    text-align: center;
    padding: 4px;
    box-sizing: border-box;
}
.mip-name {
    padding: 5px 7px;
    font-size: 11px;
    color: #c8c8d0;
    word-break: break-all;
    line-height: 1.25;
}
.mip-file {
    padding: 0 7px 6px;
    font-size: 10px;
    color: #6f6f7c;
    word-break: break-all;
}

/* ------------------------------------------------------------------ *
 * "current entry" highlight inside the RAW LiteGraph context menu.
 *
 * Used when the picture modal is not shown (no interception, a modal is
 * already open, or the menu does not qualify as a model list). Without
 * this the built-in ComboWidget menu is a flat list where the entry that
 * is actually in use is indistinguishable from the rest.
 * ------------------------------------------------------------------ */
.litegraph.litecontextmenu .litemenu-entry.mip-menu-current {
    background: rgba(91,194,126,.20) !important;
    border-left: 8px solid #5bc27e;
    padding-left: 12px;
    color: #d9ffe8 !important;
    font-weight: 700;
}
.litegraph.litecontextmenu .litemenu-entry.mip-menu-current::after {
    content: "\u5f53\u524d";   /* badge text: the two-character word "current" */
    float: right;
    margin-left: 12px;
    padding: 0 6px;
    border-radius: 999px;
    background: #5bc27e;
    color: #08210f;
    font-size: 10px;
    font-weight: 700;
    line-height: 16px;
}

/* ------------------------------------------------------------------ *
 * Architecture / conflict colouring (model_conflict.js)
 *
 *   red  = this model's architecture family differs from the workflow's
 *   blue = compatible
 *   green = currently in use (the .mip-sel / .mip-badge styling above)
 *
 * Green always wins for the active card, hence the :not(.mip-sel) guards.
 * ------------------------------------------------------------------ */
.mip-card.mip-cf-red:not(.mip-sel) {
    border-color: #ff5f56;
    box-shadow: 0 0 0 2px #ff5f56 inset;
    background: #3a1f22;
}
.mip-card.mip-cf-blue:not(.mip-sel) {
    border-color: #3d8bfd;
    box-shadow: 0 0 0 2px #3d8bfd inset;
    background: #1d2739;
}
.mip-card.mip-cf-red:hover:not(.mip-sel) { border-color: #ff8b84; }
.mip-card.mip-cf-blue:hover:not(.mip-sel) { border-color: #6ba8ff; }

/* small architecture tag in the top-right corner */
.mip-arch {
    position: absolute;
    top: 5px;
    right: 5px;
    z-index: 2;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 999px;
    background: #4a4a55;
    color: #f0f0f4;
    box-shadow: 0 1px 4px rgba(0,0,0,.5);
    max-width: 72%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
/* The architecture tag keeps its verdict colour even on the active card, so
   "green ring = in use" and "red/blue tag = compatible?" are both readable. */
.mip-cf-red .mip-arch { background: #ff5f56; color: #2b0b09; }
.mip-cf-blue .mip-arch { background: #3d8bfd; color: #08142b; }

/* baseline + tally line appended to the "当前: ..." row */
.mip-legend {
    margin-left: 14px;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
.mip-legend .mip-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #6f6f7c;
    display: inline-block;
    margin-right: 6px;
}
.mip-legend .mip-tally { display: inline-flex; gap: 6px; }
.mip-legend .mip-chip {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 7px;
    border-radius: 999px;
    background: #2b2b33;
    color: #a9a9b4;
}
.mip-legend .mip-hist { color: #6f6f7c; }
`;

let cssInjected = false;
function injectCss() {
    if (cssInjected) return;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    cssInjected = true;
}

/* ------------------------------------------------------------------ *
 * Widget value helpers (combo widgets may store a raw string or a
 * {content, image} object depending on the ComfyUI version)
 * ------------------------------------------------------------------ */

function readWidgetValue(widget) {
    const raw = widget?.value;
    if (raw == null) return "";
    if (typeof raw === "string") return raw;
    if (typeof raw === "object" && typeof raw.content === "string") return raw.content;
    return String(raw);
}

function writeWidgetValue(widget, name) {
    const raw = widget?.value;
    if (raw !== null && typeof raw === "object" && "content" in raw) {
        widget.value = { ...raw, content: name };
    } else {
        widget.value = name;
    }
    widget.callback?.(widget.value);
}

/* ------------------------------------------------------------------ *
 * Knowing WHICH model is currently in use
 *
 * A model picker is built from a plain array of names (ComfyUI's own
 * ComboWidget does exactly this for LoraLoader / CheckpointLoaderSimple):
 *
 *     new LiteGraph.ContextMenu(["a.safetensors", ...], { event, callback })
 *
 * Nothing in that call says which entry is the active one, so a picker that
 * replaces the menu cannot mark the current model unless it asks the widget
 * that opened the menu. `widget.value` IS the current model.
 *
 * `ComboWidget.onClick()` builds its ContextMenu synchronously, so wrapping
 * onClick lets us hold the widget for exactly the lifetime of that call.
 * ------------------------------------------------------------------ */

/** Combo widget whose menu is being opened right now (null otherwise). */
let pendingCombo = null;

/** Set for the duration of one ContextMenu construction: highlight entries
 *  whose normalised name equals this key. */
let menuHighlightKey = "";
let menuHighlightArmed = false;

/**
 * Wrap a combo widget's onClick so the widget (and therefore its current
 * value) is visible to the ContextMenu interception below.
 *
 * Per-instance on purpose: ComboWidget instances are what
 * LGraphCanvas.processWidgetClick calls, and this works without reaching for
 * the class object, which is not exposed to extensions.
 */
function armComboWidget(widget) {
    if (!widget || widget.__mipArmed) return;
    if (widget.type !== "combo") return;
    const orig = widget.onClick;
    if (typeof orig !== "function") return;

    const wrapper = function (opts) {
        const prev = pendingCombo;
        pendingCombo = { widget: this, node: opts?.node ?? this.node ?? null };
        try {
            return orig.call(this, opts);
        } finally {
            pendingCombo = prev;
        }
    };

    // Non-enumerable so this bookkeeping stays invisible to anything that
    // walks or serialises a widget's own properties.
    try {
        Object.defineProperty(widget, "__mipArmed", {
            value: true, writable: false, enumerable: false, configurable: true,
        });
        Object.defineProperty(widget, "onClick", {
            value: wrapper, writable: true, enumerable: false, configurable: true,
        });
    } catch {
        // Fall back to plain assignment if the widget refuses redefinition.
        widget.__mipArmed = true;
        widget.onClick = wrapper;
    }
}

/** Arm every combo widget of a node (safe to call repeatedly). */
function armNodeCombos(node) {
    const widgets = node?.widgets;
    if (!Array.isArray(widgets)) return;
    for (const w of widgets) {
        try { armComboWidget(w); } catch { /* never break node creation */ }
    }
}

/** Normalised "current model" key of the combo that just opened a menu. */
function comboCurrentKey(combo) {
    if (!combo?.widget) return "";
    return normalizeName(readWidgetValue(combo.widget));
}

/**
 * Tag the currently-used entry inside a LiteGraph context menu.
 *
 * Hooks ContextMenu.addItem (the single place every entry goes through) and
 * adds the `mip-menu-current` class when the entry matches the armed key.
 * Doing nothing unless armed keeps this from touching unrelated menus.
 */
function installMenuItemHighlight(LG) {
    const proto = LG?.ContextMenu?.prototype;
    if (!proto || proto.__mipAddItemWrapped) return;
    const orig = proto.addItem;
    if (typeof orig !== "function") {
        console.warn(`[${EXT_NAME}] ContextMenu.addItem not found; menu highlight disabled`);
        return;
    }

    proto.addItem = function (name, value, options) {
        const element = orig.apply(this, arguments);
        try {
            if (
                menuHighlightArmed &&
                element &&
                !element.classList.contains("separator") &&
                !element.classList.contains("mip-menu-current")
            ) {
                // `name` is what the user reads; `value` is what the caller
                // passed. Either may be the model name, so accept both.
                const nameKey = normalizeName(name == null ? "" : String(name));
                const valueKey = typeof value === "string" ? normalizeName(value) : "";
                if (nameKey === menuHighlightKey || valueKey === menuHighlightKey) {
                    element.classList.add("mip-menu-current");
                }
            }
        } catch { /* decoration must never break a menu */ }
        return element;
    };
    proto.__mipAddItemWrapped = true;
    console.log(`[${EXT_NAME}] context-menu current-entry highlight installed`);
}

/**
 * Bring the highlighted entry into view. Only scrolls when the menu itself is
 * scrollable - otherwise scrollIntoView would scroll the page/canvas instead.
 */
function scrollCurrentEntryIntoView(menu) {
    try {
        const root = menu?.root;
        if (!root || typeof root.querySelector !== "function") return;
        const current = root.querySelector(".mip-menu-current");
        if (!current) return;
        if (root.scrollHeight > root.clientHeight + 2) {
            current.scrollIntoView({ block: "nearest" });
        }
    } catch { /* decoration must never break a menu */ }
}

/** Thumbnail size, remembered across sessions. */
function loadCellWidth() {
    try {
        const v = Number(localStorage.getItem(CELL_STORE_KEY));
        if (Number.isFinite(v) && v >= CELL_MIN && v <= CELL_MAX) return v;
    } catch { /* ignore */ }
    return CELL_DEFAULT;
}
function saveCellWidth(v) {
    try { localStorage.setItem(CELL_STORE_KEY, String(v)); } catch { /* ignore */ }
}

/* ------------------------------------------------------------------ *
 * Modal
 * ------------------------------------------------------------------ */

/** Models already used this session, keyed by kind. Shown as a quick strip. */
const recentlyUsed = { checkpoints: [], loras: [], vae: [] };

class ModelPickerModal {
    /**
     * @param node    owning node (may be null for interception-originated opens)
     * @param widget  combo widget to write the selection into (may be null)
     * @param kind    "checkpoints" | "loras"
     * @param opts    { title?, showSize?, apply?, current? }
     *                apply(name, close): custom handler used by the universal
     *                ContextMenu interception, which must call the original
     *                menu item's callback instead of writing a widget.
     *                current: normalised name of the model currently in use,
     *                used when there is no widget to read (interception mode).
     */
    constructor(node, widget, kind, opts = {}) {
        this.node = node;
        this.widget = widget;
        this.kind = kind;
        this.title = opts.title || LABEL[kind] || kind;
        this.showSize = opts.showSize !== false;
        this.apply = typeof opts.apply === "function" ? opts.apply : null;
        /** Normalised name of the active model, if it could be determined. */
        this.currentName = opts.current ? normalizeName(opts.current) : null;
        this.items = [];
        /** Conflict check result for this kind (see model_conflict.js). */
        this.status = null;
        this.query = "";
        this.cellWidth = loadCellWidth();
        this.buildDom();
        openModals.add(this);
        this.load();
    }

    /** Normalised name of the model currently in use (widget value or hint). */
    currentKey() {
        if (this.widget) {
            const v = readWidgetValue(this.widget);
            if (v) return normalizeName(v);
        }
        return this.currentName || "";
    }

    buildDom() {
        injectCss();

        // ---- backdrop (clicking it closes) ----
        this.backdrop = el("div", null);
        this.backdrop.className = "mip-backdrop";
        this.onBackdropDown = (e) => {
            if (e.target === this.backdrop) this.destroy();
        };
        this.backdrop.addEventListener("pointerdown", this.onBackdropDown);

        // ---- modal ----
        this.modal = el("div", null);
        this.modal.className = "mip-modal";
        // Keep canvas shortcuts (delete, etc.) from firing while typing here.
        this.modal.addEventListener("keydown", (e) => {
            e.stopPropagation();
            if (e.key === "Escape") { e.preventDefault(); this.destroy(); }
        });

        // ---- header ----
        const head = el("div", null);
        head.className = "mip-head";

        this.titleEl = el("div", null, this.title);
        this.titleEl.className = "mip-title";

        this.countEl = el("div", null, "\u2026");
        this.countEl.className = "mip-count";

        this.searchEl = el("input", null);
        this.searchEl.className = "mip-search";
        this.searchEl.type = "text";
        this.searchEl.placeholder = MSG.search;
        this.searchEl.addEventListener("input", () => {
            this.query = this.searchEl.value.trim().toLowerCase();
            this.renderGrid();
        });

        // ---- size slider (the requested enlargement control) ----
        const sizeWrap = el("div", null);
        sizeWrap.className = "mip-size";
        const sizeLabel = el("span", null, MSG.size);
        this.sizeEl = el("input", null);
        this.sizeEl.type = "range";
        this.sizeEl.min = String(CELL_MIN);
        this.sizeEl.max = String(CELL_MAX);
        this.sizeEl.step = String(CELL_STEP);
        this.sizeEl.value = String(this.cellWidth);
        this.sizeEl.addEventListener("input", () => {
            this.cellWidth = Number(this.sizeEl.value);
            this.applyCellWidth();
            saveCellWidth(this.cellWidth);
        });
        sizeWrap.append(sizeLabel, this.sizeEl);
        // Only honoured when a caller explicitly asks for showSize: false - every
        // current open path (node button + intercepted native model menu) keeps
        // the slider visible, so users can resize the thumbnails wherever they
        // opened the picker.  See the takeover call site for the history.
        if (!this.showSize) sizeWrap.style.display = "none";

        const spacer = el("div", null);
        spacer.className = "mip-spacer";

        const closeBtn = el("button", null, "\u2715");
        closeBtn.className = "mip-btn mip-close";
        closeBtn.title = MSG.close;
        closeBtn.addEventListener("click", () => this.destroy());

        head.append(this.titleEl, this.countEl, this.searchEl, sizeWrap, spacer, closeBtn);

        // ---- current selection ----
        this.currentEl = el("div", null);
        this.currentEl.className = "mip-current";

        // ---- body / grid ----
        this.bodyEl = el("div", null);
        this.bodyEl.className = "mip-body";
        // Stop wheel/scroll from reaching the graph canvas underneath, which
        // would otherwise zoom the canvas and make this dialog appear to grow.
        this.onWheel = (e) => e.stopPropagation();
        this.bodyEl.addEventListener("wheel", this.onWheel, { passive: false });

        // ---- hint footer ----
        const footer = el("div", null);
        footer.style.cssText =
            "flex:0 0 auto;padding:7px 16px;border-top:1px solid rgba(255,255,255,.08);" +
            "color:#6f6f7c;font-size:11px;background:#141419;";
        footer.textContent = MSG.hint;

        this.modal.append(head, this.currentEl, this.bodyEl, footer);
        this.backdrop.appendChild(this.modal);
        document.body.appendChild(this.backdrop);
        this.applyCellWidth();

        // Escape anywhere, and block wheel/zoom on the backdrop too.
        this.onKey = (e) => {
            if (e.key !== "Escape") return;
            // Do not steal Escape from a ComfyUI dialog that is above us.
            const others = document.querySelectorAll(".p-dialog, .comfy-modal");
            if (others.length && !this.backdrop.contains(document.activeElement)) return;
            e.preventDefault();
            e.stopPropagation();
            this.destroy();
        };
        document.addEventListener("keydown", this.onKey, true);
        this.onBackdropWheel = (e) => e.stopPropagation();
        this.backdrop.addEventListener("wheel", this.onBackdropWheel, { passive: false });

        // Focus the search box so typing filters immediately.
        setTimeout(() => this.searchEl.focus(), 0);
    }

    applyCellWidth() {
        this.modal.style.setProperty("--mip-cell", `${this.cellWidth}px`);
    }

    async load() {
        let failure = null;
        try {
            const res = await fetch(`${API_LIST}?kind=${encodeURIComponent(this.kind)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.items = Array.isArray(data.items) ? data.items : [];
            this.countEl.textContent =
                `${MSG.total} ${this.items.length} \u00b7 ${MSG.withImg} ${data.withPreview ?? "?"}`;
        } catch (err) {
            this.items = [];
            failure = err;
            this.countEl.textContent = MSG.loadFailed;
            console.error("[ModelImagePicker] list failed:", err);
            // Without this the user sees an empty "no models" dialog and the
            // reason never reaches ComfyUI's log (2026-09-15: the upscale picker
            // reported HTTP 400 for seven kinds and looked like an empty list).
            diag("list-failed", `kind=${this.kind}, ${String(err && err.message || err)}`);
        }
        // Architecture check against the rest of the workflow: conflicting
        // models end up red, compatible ones blue, the active one stays green.
        this.status = await statusFor(this.kind, this.items.map((it) => it.name));
        this.renderCurrent();
        this.renderGrid();
        if (failure) this.renderLoadError(failure);
    }

    /**
     * A failed list request is not the same thing as "this folder is empty":
     * say so, and offer a retry instead of pretending the models do not exist.
     */
    renderLoadError(err) {
        const box = el("div", {
            color: "#ff9d95", padding: "18px 24px", textAlign: "center",
            borderTop: "1px solid rgba(255,255,255,.08)",
        });
        box.className = "mip-error";
        box.append(el("div", null, `${MSG.loadFailed} \u00b7 ${String(err && err.message || err)}`));
        box.append(el("div", { marginTop: "4px", color: "#9a9aa6" },
            MSG.loadFailedHint));
        const retry = el("button", { marginTop: "10px" }, MSG.retry);
        retry.className = "mip-btn";
        retry.addEventListener("click", () => {
            box.remove();
            this.load();
        });
        box.appendChild(retry);
        this.bodyEl.appendChild(box);
    }

    /** Items to display: current + recent first, then the (filtered) rest. */
    visibleItems() {
        const current = this.currentKey();
        const recent = recentlyUsed[this.kind] || [];

        const rank = (name) => {
            if (normalizeName(name) === current) return 0;
            const idx = recent.indexOf(name);
            return idx === -1 ? 1000 : 1 + idx;
        };

        let list = this.items.slice();
        if (this.query) {
            list = list.filter((it) =>
                it.name.toLowerCase().includes(this.query) ||
                (it.basename || "").toLowerCase().includes(this.query));
        } else {
            list.sort((a, b) => rank(a.name) - rank(b.name));
        }
        return list;
    }

    /** Display name of the model currently in use, or "" when unknown. */
    currentDisplay() {
        const key = this.currentKey();
        if (!key) return "";
        const hit = this.items.find((it) => normalizeName(it.name) === key);
        return hit ? (hit.basename || hit.name) : key;
    }

    renderCurrent() {
        this.currentEl.textContent = "";
        this.currentEl.append(`${MSG.current}: `);
        const shown = this.currentDisplay();
        this.currentEl.append(el("b", null, shown || MSG.none));
        // baseline architecture + conflict/compatible tally
        if (this.status) this.currentEl.appendChild(buildLegend(this.status));
    }

    renderGrid() {
        this.bodyEl.textContent = "";

        const list = this.visibleItems();
        if (!list.length) {
            const box = el("div", { color: "#7a7a86", padding: "24px", textAlign: "center" });
            box.append(el("div", null, MSG.empty));
            // Say WHICH case this is: a filtered-out list, an empty folder, or a
            // folder whose loader does not exist in this ComfyUI install.
            if (this.query) box.append(el("div", { marginTop: "6px", color: "#5a5a66" }, MSG.emptyHint));
            else if (!this.items.length) {
                box.append(el("div", { marginTop: "6px", color: "#5a5a66" },
                    `${MSG.emptyFolder} (${LABEL[this.kind] || this.kind})`));
            }
            this.bodyEl.appendChild(box);
            return;
        }

        const currentKey = this.currentKey();
        const current = currentKey;   // normalised, for comparisons
        const grid = el("div", null);
        grid.className = "mip-grid";
        let firstSelected = null;

        for (const item of list) {
            const isCurrent = !!currentKey && normalizeName(item.name) === current;
            const card = el("div", null);
            card.className = "mip-card" + (isCurrent ? " mip-sel" : "");
            card.title = item.name;
            // red = architecture conflict with the workflow, blue = compatible
            applyCardState(card, this.status, item.name);

            if (item.hasPreview) {
                const img = el("img", null);
                img.className = "mip-thumb";
                img.loading = "lazy";
                img.decoding = "async";
                img.alt = item.basename || item.name;
                img.src = `${API_IMG}?kind=${encodeURIComponent(this.kind)}&name=${encodeURIComponent(item.name)}`;
                img.addEventListener("error", () => {
                    const ph = el("div", null, MSG.noPreview);
                    ph.className = "mip-thumb-empty";
                    img.replaceWith(ph);
                });
                card.appendChild(img);
            } else {
                const ph = el("div", null, MSG.noPreview);
                ph.className = "mip-thumb-empty";
                card.appendChild(ph);
            }

            // Make the active model unmistakable: badge + tick on the name row.
            if (isCurrent) {
                const badge = el("div", null, MSG.currentBadge);
                badge.className = "mip-badge";
                card.appendChild(badge);
                firstSelected = card;
            }

            const nameEl = el("div", null,
                (isCurrent ? "\u2713 " : "") + (item.basename || item.name));
            nameEl.className = "mip-name";
            card.appendChild(nameEl);

            // Show the folder when the model lives in a subfolder.
            if (item.name.includes("/") || item.name.includes("\\")) {
                const dirEl = el("div", null, item.name.replace(/[\\/][^\\/]*$/, ""));
                dirEl.className = "mip-file";
                card.appendChild(dirEl);
            }

            // One click picks AND closes, exactly like the native menu entry this
            // picker replaced (and like the intercepted-menu path already does).
            // Keeping the modal open after a pick is what made a selection feel
            // like it needed a second, manual close.
            card.addEventListener("click", () => this.select(item.name, true));
            card.addEventListener("dblclick", (event) => event.preventDefault());
            grid.appendChild(card);
        }

        this.bodyEl.appendChild(grid);

        // Bring the active model into view (and flash it briefly) so opening the
        // picker immediately answers "which one am I using right now?".
        if (firstSelected) {
            const target = firstSelected;
            const run = () => {
                try { target.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
                catch { try { target.scrollIntoView(); } catch { /* ignore */ } }
                target.classList.add("mip-pulse");
                setTimeout(() => target.classList.remove("mip-pulse"), 1400);
            };
            if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
            else setTimeout(run, 0);
        }
    }

    select(name, close) {
        if (this.apply) {
            // Interception mode: hand the choice back to the original caller.
            // Order matters - the caller may open another menu (e.g. a submenu),
            // so the plain class is restored for the duration of the call and the
            // wrapper is re-installed only afterwards.
            const restore = this._restoreMenu;
            this.destroy();
            try {
                this.apply(name);
            } finally {
                restore?.();
            }
            return;
        }

        writeWidgetValue(this.widget, name);

        const recent = recentlyUsed[this.kind] || (recentlyUsed[this.kind] = []);
        const at = recent.indexOf(name);
        if (at !== -1) recent.splice(at, 1);
        recent.unshift(name);
        if (recent.length > 12) recent.length = 12;

        app.graph?.setDirtyCanvas(true, true);

        if (close) {
            this.destroy();
        } else {
            this.renderGrid();
            this.renderCurrent();
        }
    }

    destroy() {
        if (this._destroyed) return;
        this._destroyed = true;
        openModals.delete(this);
        document.removeEventListener("keydown", this.onKey, true);
        // Detach element listeners explicitly: a removed node keeps its listeners
        // alive for as long as anything still references it.
        this.bodyEl?.removeEventListener("wheel", this.onWheel);
        this.backdrop?.removeEventListener("wheel", this.onBackdropWheel);
        this.backdrop?.removeEventListener("pointerdown", this.onBackdropDown);
        this.backdrop?.remove();
        if (this._btn) this._btn._mipModal = null;
    }
}

/* ------------------------------------------------------------------ *
 * Attach the button to nodes
 * ------------------------------------------------------------------ */

function attachButton(node, widget, kind) {
    if (!node.widgets) return;

    node.widgets.push({
        type: "button",
        name: `mip_open_${kind}`,
        value: null,
        y: 0,
        size: [0, 0],
        // never serialized into the workflow
        options: { serialize: false },
        draw(ctx, nd, widgetWidth, y, H) {
            const w = widgetWidth - 6;
            this.y = y;
            this.size = [w, H];
            ctx.save();
            ctx.fillStyle = "#2f2f38";
            ctx.strokeStyle = "rgba(255,255,255,.22)";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.rect(3, y + 1, w, H - 2);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = "#eaeaf0";
            ctx.font = "12px system-ui, 'Microsoft YaHei', sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(`\u25a3  ${LABEL[kind]}`, 3 + w / 2, y + H / 2);
            ctx.restore();
        },
        mouse(e, pos, nd) {
            if (e.type !== "pointerdown" && e.type !== "pointerup") return false;
            if (e.type !== "pointerup") return true;
            if (pos[0] < 3 || pos[0] > this.size[0] - 3 ||
                pos[1] < this.y || pos[1] > this.y + this.size[1]) {
                return false;
            }
            openModal(nd, widget, kind, this);
            return true;
        },
    });

    node.setSize?.([
        Math.max(node.size?.[0] ?? 0, 300),
        (node.size?.[1] ?? 0) + 26,
    ]);

    app.graph?.setDirtyCanvas(true, true);
}

/** Open the modal for a node, or bring the existing one back into view. */
function openModal(node, widget, kind, btnWidget, opts = {}) {
    // Whatever native menu is still up is now redundant: the modal IS the
    // picker.  Leaving it behind means dismissing two overlays.
    closeNativeMenus();
    if (btnWidget) {
        const existing = btnWidget._mipModal;
        if (existing && !existing._destroyed) {
            existing.backdrop.remove();
            document.body.appendChild(existing.backdrop);
            existing.searchEl?.focus();
            return existing;
        }
    }
    const modal = new ModelPickerModal(node, widget, kind, opts);
    if (btnWidget) {
        modal._btn = btnWidget;
        btnWidget._mipModal = modal;
    }
    return modal;
}

/* ------------------------------------------------------------------ *
 * Universal interception of model-picker context menus
 *
 * Extensions such as ComfyUI_JosiaNodes build their LoRA list with
 *     new LiteGraph.ContextMenu(items, { event, ... })
 * where items are plain strings naming models. ComfyUI's ContextMenu cannot
 * render images (addItem() only sets textContent/innerHTML), so instead of
 * trying to decorate the menu we replace it with this modal.
 *
 * The wrapper calls the ORIGINAL constructor first, so behaviour stays correct
 * even if we bail out, and so the caller still receives a real ContextMenu.
 * ------------------------------------------------------------------ */

function normalizeKey(name) {
    return String(name).replace(/\\/g, "/").toLowerCase();
}

/**
 * The "this one is active" marker some extensions prepend to a menu entry,
 * e.g. ComfyUI_JosiaNodes sends "\u2713 hassakuXLIllustrious_v13StyleA.safetensors".
 */
const CURRENT_MARKER = /^[\s\u2713\u2714\u221a\u2705\u2022*]+/;

/**
 * Normalise a name for lookups.
 *
 * Only the known "current entry" markers are stripped.  Do NOT go back to
 * stripping every leading non-alphanumeric character: a model file may legally
 * start with one, and `[Artstyle]_SomethingWeird_Geekpower_[PDXL].safetensors`
 * used to be mangled into `artstyle]_...`, which no longer matched the index,
 * which made detectModelMenu() reject the WHOLE menu - the LoRA picker simply
 * stopped opening (2026-09-15, user report "我选择Lora哪个弹窗怎么没了").
 */
function normalizeName(name) {
    return normalizeKey(String(name).replace(CURRENT_MARKER, ""));
}

/**
 * Historic, looser strip: any run of leading non-alphanumeric glyphs.  Kept as
 * a LAST-RESORT lookup only, so unknown marker glyphs from other extensions
 * still resolve - without ever breaking names that legitimately start with one.
 */
function normalizeNameLoose(name) {
    return normalizeKey(String(name).replace(/^[^0-9A-Za-z\u4e00-\u9fff]+/, ""));
}

/**
 * Resolve one menu entry against the model index: exact name first, then the
 * marker-stripped form, then the historic loose form.
 */
function lookupModel(raw) {
    for (const key of [normalizeKey(raw), normalizeName(raw), normalizeNameLoose(raw)]) {
        const hit = modelIndex.get(key);
        if (hit) return { key, hit };
    }
    return null;
}

/** Never flood the log with the same unknown name (diag() is capped anyway). */
const unknownMenuEntries = new Set();

/**
 * "The picker did not open" used to be undiagnosable: one entry the index does
 * not know silently vetoes the entire menu.  Now the offending name is logged.
 */
function diagUnknownMenuEntry(raw) {
    const key = normalizeKey(raw);
    if (unknownMenuEntries.has(key) || unknownMenuEntries.size >= 5) return;
    unknownMenuEntries.add(key);
    diag("menu-unknown-entry",
        `${JSON.stringify(raw)} is not in the model index (${modelIndex.size} names)` +
        " -> whole menu left untouched");
}

function basenameOf(name) {
    const norm = String(name).replace(/\\/g, "/");
    return norm.split("/").pop() || norm;
}

async function loadModelLists() {
    if (modelListsLoaded) return;
    if (modelListsPromise) return modelListsPromise;

    modelListsPromise = (async () => {
        const addNames = (kind, values) => {
            if (!Array.isArray(values)) return;
            for (const name of values) {
                if (typeof name !== "string") continue;
                const key = normalizeKey(name);
                const existing = modelIndex.get(key);
                if (!existing) modelIndex.set(key, [kind]);
                else if (!existing.includes(kind)) existing.push(kind);
            }
        };

        // 1) The backend index is authoritative and also covers kinds that have
        //    no loader node of their own (textual inversions).
        try {
            const backendKinds = await indexKinds();
            for (const [kind, values] of Object.entries(backendKinds)) addNames(kind, values);
        } catch (err) {
            console.warn(`[${EXT_NAME}] backend model index unavailable:`, err);
        }

        // 2) Node definitions (checkpoints first: on a name collision it
        //    becomes the default kind).
        try {
            const res = await fetch("/object_info");
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const info = await res.json();

            const kinds = [
                ["checkpoints", "CheckpointLoaderSimple", "ckpt_name"],
                ["loras", "LoraLoader", "lora_name"],
                ["vae", "VAELoader", "vae_name"],
                ["controlnet", "ControlNetLoader", "control_net_name"],
                ["diffusion_models", "UNETLoader", "unet_name"],
                ["text_encoders", "CLIPLoader", "clip_name"],
                ["upscale_models", "UpscaleModelLoader", "model_name"],
                ["ultralytics", "UltralyticsDetectorProvider", "model_name"],
                ["sams", "SAMLoader", "model_name"],
            ];
            for (const [kind, nodeName, field] of kinds) {
                addNames(kind, info?.[nodeName]?.input?.required?.[field]?.[0]);
            }
        } catch (err) {
            console.warn(`[${EXT_NAME}] could not index /object_info model names:`, err);
            diag("index-failed", String(err));
        }

        if (modelIndex.size) {
            modelListsLoaded = true;
            console.log(`[${EXT_NAME}] indexed ${modelIndex.size} model names for menu interception`);
            diag("index-built", `names=${modelIndex.size}`);
        }
    })();

    return modelListsPromise;
}

/** Sentinel entries that may appear in a model combo without being a model. */
const SENTINELS = new Set(["none", "null", "undefined", "n/a", "", "\u65e0", "\u7a7a"]);

/**
 * Report a diagnostic event to the backend so it shows up in ComfyUI's log.
 * This is how "the picker did not open" can be diagnosed without devtools.
 */
let diagCount = 0;
function diag(stage, detail = "") {
    if (diagCount++ > 120) return;   // keep the log from being flooded
    try {
        fetch("/modelpreview/debug", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stage, detail: String(detail).slice(0, 400) }),
        }).catch(() => {});
    } catch { /* never let diagnostics break anything */ }
}

/**
 * Normalise one context-menu entry to the model name it stands for, or null.
 *
 * Extensions use two shapes (both verified against a live page):
 *   - plain strings:            ["a.safetensors", "b.safetensors"]
 *   - objects with .content:    [{ content: "a.safetensors", callback: fn }]
 *     (this is what ComfyUI_JosiaNodes' showLM builds)
 *
 * Entries carrying submenu/disabled markers or a non-string content are not
 * model names and make the whole menu ineligible.
 */
function menuItemName(item) {
    if (typeof item === "string") return item;
    if (item && typeof item === "object" && !Array.isArray(item)) {
        if (item.has_submenu || item.submenu || item.disabled) return null;
        if (typeof item.content === "string" && item.content) return item.content;
    }
    return null;
}

/**
 * Decide whether a context menu is a model picker.
 * Returns { kind, names, entries, currentName } or null.
 *
 * A menu qualifies as soon as MIN_MODELS of its entries resolve to a known
 * model.  Unknown entries used to veto the WHOLE menu, and that is exactly how
 * one oddly named model file made the picker stop opening altogether
 * (2026-09-15).  A small number of them is now tolerated - they are simply not
 * offered in the modal, which gets its list from the backend anyway - while a
 * menu that is mostly unknown is still left untouched, so unrelated menus (a
 * node's right-click menu, rgthree's slot menu, ...) can never be hijacked.
 *
 * Submenus and separators still veto: those are not plain model lists.
 */
const MIN_MODELS = 3;
/** Tolerated unknown entries: at most this many, and at most this share of the menu. */
const MAX_UNKNOWN = 3;
const MAX_UNKNOWN_SHARE = 0.2;

function detectModelMenu(items, options, combo) {
    if (!Array.isArray(items)) return null;
    if (options?.parentMenu) return null;          // never touch submenus
    if (!items.length) return null;

    // A combo widget that opened this menu is authoritative about the model
    // currently in use: ComfyUI's own menus carry no current-entry marker.
    const widgetKey = comboCurrentKey(combo);

    const names = [];      // clean display name for each model entry
    const entries = [];    // the original entries, aligned with `names`
    const kinds = new Map();
    const unknown = [];    // entries that are not in the index (tolerated, not offered)
    let currentName = null;

    for (const item of items) {
        if (item === null) return null;            // separator => not a model list

        const raw = menuItemName(item);
        if (raw === null) return null;             // submenu / unknown shape

        const found = lookupModel(raw);

        // Extensions mark the entry that is currently in use with a leading
        // glyph (ComfyUI_JosiaNodes sends "\u2713 <name>"). Remember it so the
        // picker can highlight the model that is actually active.
        if (currentName === null && /^[\u2713\u2714\u221a\u2705\u2022*]\s*/.test(raw)) {
            if (found) currentName = normalizeName(raw);
        }

        const key = normalizeName(raw);
        if (SENTINELS.has(key)) continue;          // "None" / "\u2713 None" etc.

        if (!found) {                              // not a model the index knows
            unknown.push(raw);
            continue;
        }

        names.push(raw);
        entries.push(item);
        for (const k of found.hit) kinds.set(k, (kinds.get(k) || 0) + 1);
    }

    if (names.length < MIN_MODELS) return null;

    const allowedUnknown = Math.max(MAX_UNKNOWN, Math.floor(names.length * MAX_UNKNOWN_SHARE));
    for (const raw of unknown.slice(0, 2)) diagUnknownMenuEntry(raw);
    if (unknown.length > allowedUnknown) return null;

    // The live widget value wins; the "✓" text hint is only a fallback for
    // menus that extensions build themselves (e.g. ComfyUI_JosiaNodes).
    if (widgetKey) currentName = widgetKey;

    let best = null;
    for (const [k, count] of kinds) {
        if (!best || count > best[1]) best = [k, count];
    }
    if (!best) return null;

    return { kind: best[0], names, entries, currentName };
}

/** Poll handle used while waiting for LiteGraph to show up. */
let interceptorTimer = null;
let interceptorTries = 0;
const INTERCEPTOR_MAX_TRIES = 80;   // 80 * 250ms = 20s

/**
 * Wrap LiteGraph.ContextMenu. Safe to call repeatedly: returns true once armed.
 *
 * The class only exists on window after ComfyUI's frontend has initialised
 * LiteGraph, which does not necessarily happen before extensions' setup() runs.
 * So when it is missing we retry instead of giving up permanently.
 */
function installContextMenuInterceptor() {
    const LG = globalThis.LiteGraph;
    const Original = LG?.ContextMenu;

    if (typeof Original !== "function") {
        // Retry until LiteGraph appears (or we give up after ~20s).
        if (interceptorTimer === null && interceptorTries < INTERCEPTOR_MAX_TRIES) {
            interceptorTimer = setTimeout(() => {
                interceptorTimer = null;
                interceptorTries++;
                if (!installContextMenuInterceptor() && interceptorTries >= INTERCEPTOR_MAX_TRIES) {
                    console.warn(`[${EXT_NAME}] LiteGraph.ContextMenu never appeared; interception disabled`);
                    diag("interceptor-failed", "LiteGraph.ContextMenu never appeared within 20s");
                }
            }, 250);
        }
        return false;
    }

    if (Original.__mipWrapped) return true;

    diag("interceptor-armed",
        `LiteGraph=${typeof LG}, ContextMenu=${typeof Original}, tries=${interceptorTries}`);

    function PickerContextMenu(items, options) {
        // The combo widget that opened this menu, if any. `pendingCombo` is set
        // only for the duration of its synchronous onClick call, so it is exact.
        const combo = pendingCombo;
        const widgetKey = comboCurrentKey(combo);

        // Detection is a pure function of the passed items, so it can run before
        // construction; the result decides how the raw menu gets decorated.
        let detected = null;
        try {
            detected = detectModelMenu(items, options, combo);
        } catch (err) {
            console.warn(`[${EXT_NAME}] menu detection skipped:`, err);
        }

        // Highlight the entry that is currently in use inside the RAW menu too:
        // if the modal does not take over, the plain list must still say which
        // model is active. ContextMenu builds all entries synchronously in its
        // constructor, so the hint is cleared as soon as construction returns.
        const prevArmed = menuHighlightArmed;
        const prevKey = menuHighlightKey;
        const menuKey = widgetKey || detected?.currentName || "";
        menuHighlightKey = menuKey;
        menuHighlightArmed = menuKey !== "";

        // Build the real menu first: keeps behaviour intact if we decide to keep it.
        let menu;
        try {
            menu = new Original(items, options);
        } finally {
            menuHighlightArmed = prevArmed;
            menuHighlightKey = prevKey;
        }
        scrollCurrentEntryIntoView(menu);

        try {
            const shape = Array.isArray(items)
                ? `n=${items.length}, first=${JSON.stringify(
                    (Array.isArray(items) ? items[0] : undefined) && typeof items[0] === "object"
                        ? Object.keys(items[0]).join("/")
                        : items[0]).slice(0, 60)}`
                : `not-array(${typeof items})`;
            // Drop stale entries before deciding whether another modal may open.
            pruneOpenModals();
            diag("menu-observed",
                `${shape} -> ${detected ? `DETECTED ${detected.kind}` : "not-a-model-menu"}` +
                `, current="${menuKey || "-"}", source=${combo ? "widget" : "menu-text"}` +
                `, indexed=${modelIndex.size}, openModals=${openModals.size}`);
            // Never stack two of our modals, and only take over plain left-click menus.
            //
            // `takeoverPending` covers the gap between "a model menu was
            // detected" and "our modal exists": during that await `openModals`
            // is still empty, so a second menu - a double click, or a click
            // while the model index is still loading - used to open a SECOND
            // picker.  Closing one left the other on screen, which is the
            // "have to close it twice" report.  Duplicates are now dropped.
            if (detected && (openModals.size > 0 || takeoverPending)) {
                diag("menu-duplicate-dropped",
                    `openModals=${openModals.size}, pending=${takeoverPending}`);
                if (menu.root?.isConnected) menu.close();
            } else if (detected) {
                // The one line that says "a model menu was taken over and the
                // modal is about to open" - the answer to "did my click reach
                // the picker or not".
                diag("menu-takeover",
                    `kind=${detected.kind}, models=${detected.names.length}, ` +
                    `current=${detected.currentName || "-"}`);
                // Map the displayed name back to the entry the caller passed, so we
                // can hand it over unchanged (it may carry its own callback).
                const byName = new Map();
                detected.names.forEach((nm, i) => {
                    const key = normalizeName(nm);
                    if (!byName.has(key)) byName.set(key, detected.entries[i]);
                });

                takeoverPending = true;
                loadModelLists().finally(() => {
                    takeoverPending = false;
                    if (menu.root?.isConnected) menu.close();
                    // Passing the widget lets the modal read the active model
                    // live, so it can badge, ring and scroll to it. `current` is
                    // only the fallback for menus that carry a "\u2713" marker.
                    const modal = openModal(
                        combo?.node ?? null,
                        combo?.widget ?? null,
                        detected.kind,
                        null,
                        {
                            title: `${LABEL[detected.kind] || detected.kind} \u00b7 ${detected.names.length}`,
                            // The size slider belongs to EVERY open path, including
                            // this one.  It used to be suppressed here ("pick
                            // quickly, don't fine-tune the layout"), but that is
                            // where the user actually lives: opening the model
                            // list from a node widget IS the common case, so the
                            // control was missing exactly where it was wanted
                            // (2026-09-16 report "模型弹窗上面的调整图片大小没有了").
                            // The chosen width is persisted in localStorage anyway,
                            // so it stays put across opens.
                            showSize: true,
                            current: detected.currentName || null,
                            apply: (name) => {
                                // Hand control back exactly the way the original menu would
                                // have: an item callback if the entry had one, otherwise
                                // options.callback(name, options, event) with `this` bound
                                // to the menu instance.
                                //
                                // byName is keyed by the NORMALISED name (lowercased), so
                                // the lookup must normalise too.
                                LG.ContextMenu = Original;
                                const item = byName.get(normalizeName(name));
                                const itemCb = item && typeof item === "object" ? item.callback : null;
                                if (typeof itemCb === "function") {
                                    itemCb.call(menu, item, options, options?.event);
                                } else if (typeof options?.callback === "function") {
                                    options.callback.call(menu, name, options, options?.event);
                                }
                            },
                        }
                    );
                    // select() calls this after apply(), to re-arm the interceptor.
                    modal._restoreMenu = () => { LG.ContextMenu = PickerContextMenu; };
                });
            }
        } catch (err) {
            console.warn(`[${EXT_NAME}] menu interception skipped:`, err);
        }

        return menu;
    }

    PickerContextMenu.prototype = Original.prototype;
    PickerContextMenu.__mipWrapped = true;
    LG.ContextMenu = PickerContextMenu;

    installMenuItemHighlight(LG);

    // Also expose it the way ComfyUI exposes the class globally.
    if (globalThis.ContextMenu === Original) globalThis.ContextMenu = PickerContextMenu;

    console.log(`[${EXT_NAME}] LiteGraph.ContextMenu interception installed`);
    return true;
}

/* ------------------------------------------------------------------ *
 * Extension entry point
 * ------------------------------------------------------------------ */

app.registerExtension({
    name: EXT_NAME,

    /**
     * Runs once the app object graph exists. window.LiteGraph may not be set at
     * this point, so the installer retries on its own (see below for the extra
     * hooks that also retry).
     */
    async setup() {
        installContextMenuInterceptor();
        loadModelLists();
        // Nodes restored with the current workflow are already in the graph.
        try {
            for (const n of app.graph?._nodes ?? []) armNodeCombos(n);
        } catch { /* ignore */ }
    },

    /** Retry hooks: whichever fires first after LiteGraph exists arms us. */
    async afterConfigureGraph() {
        installContextMenuInterceptor();
        try {
            for (const n of app.graph?._nodes ?? []) armNodeCombos(n);
        } catch { /* ignore */ }
    },
    loadedGraphNode(node) {
        installContextMenuInterceptor();
        armNodeCombos(node);
    },

    /**
     * Fires for every node once its widgets exist, which is what makes the
     * "which model is active" lookup work for combo widgets - including the
     * ones ComfyUI creates itself for LoraLoader / CheckpointLoaderSimple.
     */
    nodeCreated(node) {
        armNodeCombos(node);
        installContextMenuInterceptor();
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // By the time node definitions are registered, LiteGraph is normally up.
        installContextMenuInterceptor();

        const kind = NODE_KIND[nodeData?.name];
        const field = NODE_FIELD[nodeData?.name];
        if (!kind || !field) return;

        // Only attach when the node definition really declares that input.
        const declared = nodeData?.input?.required?.[field] ?? nodeData?.input?.optional?.[field];
        if (!declared) {
            console.warn(`[${EXT_NAME}] ${nodeData.name} has no "${field}" input, skipping`);
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            try {
                const widget = this.widgets?.find((w) => w.name === field);
                if (!widget) {
                    console.warn(`[${EXT_NAME}] no "${field}" widget on ${nodeData.name}`);
                    return result;
                }
                attachButton(this, widget, kind);
            } catch (err) {
                console.error(`[${EXT_NAME}] attach failed on ${nodeData.name}:`, err);
            }

            return result;
        };
    },
});

console.log(`[${EXT_NAME}] loaded (checkpoints + loras, modal UI)`);

export { detectModelMenu, loadModelLists, lookupModel, normalizeName, normalizeKey, modelIndex };
