/**
 * SmartCLIP 词嵌入（Embedding）
 * =============================
 * 两件事，一个文件：
 *
 *   1. 打字补全。在提示词框里输入 `embedding:` 前缀或名字的前几个字母，候选就弹在
 *      光标下方：↑↓ 选择、Enter/Tab 插入、Esc 关闭。
 *   2. 选择弹窗。由「选择提示词」弹窗头部那个「词嵌入」按钮打开
 *      （`openEmbeddingPicker`）。卡片带侧车预览图、兼容徽标和架构短标签，判定走
 *      `/smart_clip/embeddings?family=...` —— 后端 `embedding_compat.annotate()`，
 *      与提示词词条徽标同一套结论，前端不再自己算一遍。
 *
 * 唯一能被 ComfyUI 解析的写法：
 *
 *     embedding:NAME
 *
 * 它必须是一个独立词。comfy/sd1_clip.py 按 " embedding:" / "\nembedding:" 切分，
 * 再用 str.split() 取名字，所以任何一侧粘上别的字符都会变成一个静默丢弃的未知
 * token。下面的插入函数保证两侧都有分隔符；实测（tests/probe_prompt_syntax.py）
 * `embedding:EasyNegative` 会变成 768 维词向量，裸名 `easynegative` 只会变成普通
 * 文字 token —— 所以裸名一律补前缀。
 *
 * 带权重也是合法的：`(embedding:EasyNegative:0.8)` 实测词向量权重就是 0.8
 * （token_weights() 用 rfind(":") 取权重，名字里的下划线/数字不受影响）。
 *
 * 历史：2026-09-15 曾把独立图片弹窗（含右下角悬浮按钮）和节点上的「Embedding」按钮
 * 全部删掉，只留打字补全。现在弹窗以「提示词弹窗的子弹窗」形式回来：入口只有一个，
 * 不再是全局悬浮按钮，也不再往节点上加控件；插入目标由调用方通过 opts 决定。
 *
 * 注意：这个扩展对象**不能删** —— 补全引擎就住在它的 setup() 里
 * （injectCss + bindGlobalListeners + loadItems）。
 */

import { app } from "../../scripts/app.js";

const EXT_NAME = "SmartCLIP.Embedding";
const API_LIST = "/smart_clip/embeddings";
const API_IMG = "/smart_clip/embeddings/img";
const API_FALLBACK = "/embeddings";
/** ComfyUI 唯一会解析的词嵌入写法（与 tokenizer 实测一致，见文件头注释）。 */
export const EMBEDDING_PREFIX = "embedding:";
const TEXTAREA_SELECTOR =
    "textarea.comfy-multiline-input, textarea[data-testid='dom-widget-textarea']";
const MAX_SUGGESTIONS = 12;
const MIN_PREFIX_LEN = 1;
const STORE_CELL = "scEmb.cellWidth";

const CELL_DEFAULT = 124;
const CELL_MIN = 72;
const CELL_MAX = 280;
const CELL_STEP = 8;

const MSG = {
    title: "词嵌入（Embedding）",
    search: "搜索词嵌入…",
    refresh: "刷新",
    close: "关闭",
    undo: "撤销插入",
    size: "图片大小",
    target: "插入到",
    positive: "正向提示词",
    negative: "负面提示词",
    family: "模型族",
    /** 前端说不出底模时后端按工作流兜底了（见 workflow_model.py）。 */
    familyWorkflow: "（按工作流推断）",
    empty: "没有找到 embedding。把 .pt / .safetensors 放进 ComfyUI/models/embeddings 后点「刷新」。",
    noMatch: "没有匹配项",
    loading: "加载中…",
    loadFailed: "加载失败",
    hint: "单击插入 · 双击插入并关闭 · Esc 关闭",
    picked: "已插入",
    current: "当前使用",
    noTarget: "没有插入目标（请从「选择提示词」弹窗里打开这个选择器）",
    copied: "已复制",
    copyFailed: "复制失败",
    undoDone: "已撤销上一次插入",
    undoBlocked: "插入之后内容又被改过，不能安全撤销",
    undoEmpty: "没有可撤销的插入",
};

/** 后端 embedding_compat.annotate() 的 state -> 徽标文字。 */
const COMPAT_LABEL = {
    ok: "兼容",
    partial: "半兼容",
    incompatible: "不兼容",
    missing: "未安装",
    unknown: "未知",
};

/* ------------------------------------------------------------------ *
 * State
 * ------------------------------------------------------------------ */

/** [{ name, hasPreview, compat }] per model family - compat needs a family. */
const itemsCache = new Map();
/** family key -> { family, source } the backend actually judged the list with. */
const familyMeta = new Map();
let loadPromise = null;
let loadPromiseKey = null;

/** Just the names, for the completion engine. */
let embeddings = [];

/** Completion popup. */
let popupEl = null;
let popupState = null; // { box, start, end, matches, index, hasPrefix }

/** Picker (built lazily, reused after the first open). */
let pickerEl = null;
let gridEl = null;
let searchEl = null;
let countEl = null;
let whereEl = null;
let statusEl = null;
let undoBtn = null;
let cellInput = null;
/** { family, role, getText, setText, onPick } while open, null when closed. */
let pickerOpts = null;
let flashName = "";
let cellWidth = CELL_DEFAULT;

/** Insertion history, newest last - powers "撤销插入". */
const undoStack = [];

/* ------------------------------------------------------------------ *
 * Small helpers
 * ------------------------------------------------------------------ */

function clamp(v, lo, hi) {
    return Math.min(Math.max(v, lo), hi);
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function isPromptBox(node) {
    return !!(
        node &&
        node.nodeType === 1 &&
        typeof node.matches === "function" &&
        node.matches(TEXTAREA_SELECTOR)
    );
}

function readStore(key, fallback) {
    try {
        if (typeof localStorage === "undefined") return fallback;
        const v = localStorage.getItem(key);
        return v === null ? fallback : v;
    } catch {
        return fallback;
    }
}

function writeStore(key, value) {
    try {
        if (typeof localStorage === "undefined") return;
        localStorage.setItem(key, String(value));
    } catch {
        /* private mode - ignore */
    }
}

async function copyToClipboard(text) {
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch {
        /* fall through to the legacy path */
    }
    try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
        document.body.appendChild(ta);
        if (typeof ta.select === "function") ta.select();
        const ok = typeof document.execCommand === "function" && document.execCommand("copy");
        ta.remove();
        return !!ok;
    } catch {
        return false;
    }
}

/** First character of the embedding's own name, for the placeholder tile. */
function initialOf(name) {
    const base = String(name).split(/[\\/]/).pop() || String(name);
    return base.slice(0, 1).toUpperCase() || "?";
}

/* ------------------------------------------------------------------ *
 * Embedding list
 *
 * The completion engine only needs names, but the picker needs the compat
 * verdict, and that is per model family - so the cache is keyed by family and
 * the family-less list (what setup() warms up) stays usable for completion.
 * ------------------------------------------------------------------ */

function normalizeItems(raw) {
    return (Array.isArray(raw) ? raw : [])
        // The fallback endpoint (/embeddings) answers with bare names while the
        // preview API answers with objects - accept both, or the fallback
        // silently yields an empty list.
        .map((i) => (typeof i === "string" ? { name: i } : i))
        .filter((i) => i && typeof i.name === "string" && i.name.trim())
        .map((i) => ({
            name: i.name.trim(),
            hasPreview: !!i.hasPreview,
            compat: i.compat || null,
        }));
}

async function loadItems(family = "", force = false) {
    const key = String(family || "");
    if (!force && itemsCache.has(key)) return itemsCache.get(key);
    if (!force && loadPromise && loadPromiseKey === key) return loadPromise;

    loadPromiseKey = key;
    loadPromise = (async () => {
        let items = [];
        let meta = null;
        try {
            const url = key ? `${API_LIST}?family=${encodeURIComponent(key)}` : API_LIST;
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            items = normalizeItems(data?.items);
            // The backend may have answered with a family of its own: when the
            // frontend could not identify the base model it falls back to the
            // model ComfyUI last ran, and the badge then says which one that was.
            meta = {
                family: String(data?.family || ""),
                source: String(data?.familySource || ""),
            };
        } catch (err) {
            console.warn(`[${EXT_NAME}] preview API unavailable, falling back:`, err);
            try {
                const res = await fetch(API_FALLBACK);
                const list = await res.json();
                items = normalizeItems(Array.isArray(list) ? list : []);
            } catch (err2) {
                console.error(`[${EXT_NAME}] could not load embeddings:`, err2);
                items = [];
            }
        }
        itemsCache.set(key, items);
        familyMeta.set(key, meta);
        embeddings = items.map((i) => i.name);
        console.log(`[${EXT_NAME}] ${items.length} embeddings${key ? ` (family=${key})` : ""}`
            + (meta?.source === "workflow" ? ` -> judged as ${meta.family}` : ""));
        return items;
    })();

    return loadPromise;
}

/* ------------------------------------------------------------------ *
 * Insertion into a prompt box (completion engine)
 * ------------------------------------------------------------------ */

/**
 * Work out what to write and which range to replace, so that
 * "embedding:NAME" ends up as a standalone word.
 */
function buildInsertion(value, start, end, name, usePrefix) {
    const before = value.slice(0, start);
    const after = value.slice(end);

    // Left side: needs a separator or ComfyUI never sees the keyword. Prompts
    // separate tags with commas, so use ", " after a word and a plain space
    // otherwise. Skipped when the text already ends in "embedding:" - the name
    // continues it rather than starting a new tag.
    let lead = "";
    if (usePrefix && before.length > 0 && !/[\s]$/.test(before)) {
        lead = /[A-Za-z0-9_)\]]$/.test(before) ? ", " : " ";
    }

    // Right side: keep whatever follows a separate word. A comma glued on is
    // the common case ("embedding:x,1girl") and would be unparseable.
    let tail = "";
    let trimEnd = end;
    if (after.length > 0 && !/^\s/.test(after)) {
        if (/^,\s/.test(after)) {
            tail = "";
        } else if (/^,/.test(after)) {
            trimEnd = end + 1;
            tail = ", ";
        } else {
            tail = " ";
        }
    }

    const core = usePrefix ? EMBEDDING_PREFIX + name : name;
    return { text: lead + core + tail, start, end: trimEnd };
}

/** Write into a prompt box the way ComfyUI expects to be notified. */
function writeIntoBox(box, insertion) {
    box.focus();
    if (typeof box.setRangeText === "function") {
        box.setRangeText(insertion.text, insertion.start, insertion.end, "end");
    } else {
        box.value =
            box.value.slice(0, insertion.start) +
            insertion.text +
            box.value.slice(insertion.end);
        box.selectionStart = box.selectionEnd =
            insertion.start + insertion.text.length;
    }
    // ComfyUI syncs a DOM widget through its "input" listener.
    box.dispatchEvent(new Event("input", { bubbles: true }));
}

/* ------------------------------------------------------------------ *
 * Type-ahead completion
 * ------------------------------------------------------------------ */

function currentFragment(box) {
    if (box.selectionStart !== box.selectionEnd) return null;
    const caret = box.selectionStart;
    if (caret === null || caret === undefined) return null;
    const lineStart = box.value.lastIndexOf("\n", caret - 1) + 1;
    const before = box.value.slice(lineStart, caret);
    const m = before.match(/([A-Za-z0-9_.\-]+)$/);
    if (!m) return null;
    const word = m[1];
    const start = lineStart + m.index;
    const lead = box.value.slice(0, start);
    return {
        word,
        start,
        end: caret,
        hasPrefix: lead.toLowerCase().endsWith(EMBEDDING_PREFIX),
    };
}

function matchingEmbeddings(word) {
    const q = word.toLowerCase();
    const starts = [];
    const contains = [];
    for (const name of embeddings) {
        const lower = name.toLowerCase();
        if (lower.startsWith(q)) starts.push(name);
        else if (lower.includes(q)) contains.push(name);
    }
    // Prefix matches first: "ea" should offer EasyNegative, not ng_deepnegative.
    return starts.concat(contains).slice(0, MAX_SUGGESTIONS);
}

function closePopup() {
    popupState = null;
    if (popupEl) popupEl.style.display = "none";
}

function positionPopup(box) {
    if (!popupEl) return;
    const r = box.getBoundingClientRect();
    popupEl.style.display = "block";
    const pw = popupEl.offsetWidth || 220;
    const ph = popupEl.offsetHeight || 120;
    const left = clamp(r.left, 8, Math.max(8, window.innerWidth - pw - 8));
    let top = r.bottom + 4;
    if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 4);
    popupEl.style.left = `${left}px`;
    popupEl.style.top = `${top}px`;
}

function renderPopup() {
    if (!popupEl || !popupState) return;
    popupEl.textContent = "";
    popupState.matches.forEach((name, i) => {
        const row = el("div", "sc-emb-popup-row" + (i === popupState.index ? " sc-emb-active" : ""));
        row.textContent = popupState.hasPrefix ? name : EMBEDDING_PREFIX + name;
        row.addEventListener("mousedown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            acceptCompletion(i);
        });
        popupEl.appendChild(row);
    });
    positionPopup(popupState.box);
}

function openPopup(box, fragment) {
    const matches = matchingEmbeddings(fragment.word);
    if (!matches.length) {
        closePopup();
        return;
    }
    if (!popupEl) {
        popupEl = el("div", "sc-emb-popup");
        document.body.appendChild(popupEl);
    }
    popupState = {
        box,
        start: fragment.start,
        end: fragment.end,
        matches,
        index: 0,
        hasPrefix: fragment.hasPrefix,
    };
    renderPopup();
    positionPopup(box);
}

function acceptCompletion(index = null) {
    if (!popupState) return;
    const st = popupState;
    const name = st.matches[index === null ? st.index : index];
    if (!name) return closePopup();
    writeIntoBox(
        st.box,
        buildInsertion(st.box.value, st.start, st.end, name, !st.hasPrefix)
    );
    closePopup();
}

function onPromptInput(box) {
    // 选择器开着的时候不弹补全候选：插入会写回节点文本框并派发 input，
    // 不拦的话候选层会在选择器后面闪一下（z-index 更低，看不见但会抢键）。
    if (pickerOpts) return closePopup();
    const fragment = currentFragment(box);
    if (!fragment || fragment.word.length < MIN_PREFIX_LEN) return closePopup();
    if (embeddings.some((n) => n.toLowerCase() === fragment.word.toLowerCase())) {
        if (fragment.hasPrefix) return closePopup();
    }
    openPopup(box, fragment);
}

/* ------------------------------------------------------------------ *
 * Picker - the picture grid, now a sub-dialog of the prompt dialog
 * ------------------------------------------------------------------ */

/** Names already written in the target prompt (`embedding:X`). */
function currentNames() {
    const text = String(pickerOpts?.getText?.() || "");
    const out = [];
    const re = /embedding:\s*([^,\s)\]\n]+)/gi;
    let m;
    while ((m = re.exec(text)) !== null) {
        out.push(m[1].replace(/[.。，]+$/, "").toLowerCase());
    }
    return out;
}

function isCurrent(name, current) {
    return current.includes(String(name).toLowerCase());
}

function setStatus(text, ok = true) {
    if (!statusEl) return;
    statusEl.textContent = text || "";
    statusEl.className = ok ? "sc-emb-status" : "sc-emb-status sc-emb-status-bad";
}

function updateUndo() {
    if (!undoBtn) return;
    undoBtn.disabled = undoStack.length === 0;
    undoBtn.textContent = undoStack.length
        ? `${MSG.undo} (${undoStack.length})`
        : MSG.undo;
}

function renderWhere() {
    if (!whereEl) return;
    const role = pickerOpts?.role === "negative" ? MSG.negative : MSG.positive;
    const requested = String(pickerOpts?.family || "");
    const meta = familyMeta.get(requested) || null;
    // The badge is judged against what the backend actually used, which is the
    // frontend's own answer unless it had none (then it is the workflow's).
    const family = String(meta?.family || requested || "");
    const flavour = meta?.source === "workflow" && family && family !== requested
        ? MSG.familyWorkflow : "";
    whereEl.textContent = `${MSG.target}: ${role}`
        + (family ? ` · ${MSG.family} ${family}${flavour}` : "");
}

function placeholderTile(item) {
    const tile = el("div", "sc-emb-thumb sc-emb-thumb-empty");
    tile.appendChild(el("span", "sc-emb-initial", initialOf(item.name)));
    return tile;
}

function buildCard(item, current) {
    const card = el("div", "sc-emb-card");
    card.dataset.name = item.name;

    const compat = item.compat || null;
    const state = compat?.state || "";
    // 与模型弹窗同一套颜色：红 = 不兼容（真冲突）、蓝 = 兼容、黄 = 半兼容
    // （能吃下但只有一半编码器生效，例如 SDXL 上的 768 维 SD1.5 词嵌入）、
    // 绿 = 当前使用。
    if (state === "incompatible") card.classList.add("sc-emb-cf-red");
    else if (state === "partial") card.classList.add("sc-emb-cf-amber");
    else if (state === "ok") card.classList.add("sc-emb-cf-blue");
    const used = isCurrent(item.name, current);
    if (used) card.classList.add("sc-emb-current");
    if (flashName && flashName === item.name) card.classList.add("sc-emb-picked");

    card.title = `${EMBEDDING_PREFIX}${item.name}`
        + (compat?.why ? `\n${compat.why}` : "")
        + (used ? `\n${MSG.current}` : "");

    if (item.hasPreview) {
        const thumb = el("div", "sc-emb-thumb");
        const img = document.createElement("img");
        img.className = "sc-emb-thumb-img";
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = item.name;
        img.src = `${API_IMG}?name=${encodeURIComponent(item.name)}`;
        img.addEventListener("error", () => {
            const parent = thumb.parentNode;
            if (parent) parent.replaceChild(placeholderTile(item), thumb);
        });
        thumb.appendChild(img);
        card.appendChild(thumb);
    } else {
        card.appendChild(placeholderTile(item));
    }

    card.appendChild(el("div", "sc-emb-card-name", item.name));

    // 兼容徽标：与「选择提示词」弹窗的词条徽标同源（embedding_compat.annotate）
    if (state) {
        const label = COMPAT_LABEL[state] || state;
        const short = compat.short && compat.short !== "?" ? compat.short : "";
        const badge = el("div", `sc-emb-badge sc-emb-badge-${state}`,
            short && state !== "missing" && state !== "unknown" ? `${short} · ${label}` : label);
        badge.title = compat.why || "";
        card.appendChild(badge);
    }

    if (used) card.appendChild(el("div", "sc-emb-now", MSG.current));

    const copy = el("button", "sc-emb-card-copy", "复制");
    copy.type = "button";
    copy.title = `复制 ${EMBEDDING_PREFIX}${item.name}`;
    copy.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const ok = await copyToClipboard(EMBEDDING_PREFIX + item.name);
        setStatus(ok ? `${MSG.copied} ${EMBEDDING_PREFIX}${item.name}` : MSG.copyFailed, ok);
    });
    card.appendChild(copy);
    card.appendChild(el("div", "sc-emb-card-tick", "\u2713"));

    // 单击插入（弹窗留着继续点），双击插入并关窗。
    //
    // 双击会被浏览器拆成 click, click, dblclick，所以单击必须延后一点点再执行，
    // 双击时把那个待执行的单点取消掉——否则双击会插三遍。定时器按卡片各存一份
    // （存成闭包变量），连着点两张不同的卡不会互相取消。
    let clickTimer = null;
    card.addEventListener("click", () => {
        if (clickTimer) clearTimeout(clickTimer);
        clickTimer = setTimeout(() => {
            clickTimer = null;
            pickCard(item, false);
        }, 240);
    });
    card.addEventListener("dblclick", () => {
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
        }
        pickCard(item, true);
    });
    return card;
}

function visibleItems() {
    const query = String(searchEl?.value || "").trim().toLowerCase();
    const items = itemsCache.get(String(pickerOpts?.family || "")) || [];
    if (!query) return items;
    return items.filter((i) => i.name.toLowerCase().includes(query));
}

function renderGrid() {
    if (!gridEl || !pickerOpts) return;

    const items = itemsCache.get(String(pickerOpts.family || ""));
    const current = currentNames();
    gridEl.textContent = "";
    gridEl.style.setProperty("--sc-emb-cell", `${cellWidth}px`);

    if (!items) {
        gridEl.appendChild(el("div", "sc-emb-empty", MSG.loading));
        return;
    }
    if (!items.length) {
        gridEl.appendChild(el("div", "sc-emb-empty", MSG.empty));
        return;
    }

    // 已经在提示词里的排最前（和模型弹窗"当前使用"排最前一个道理）
    const shown = visibleItems().slice().sort((a, b) => {
        const ua = isCurrent(a.name, current) ? 0 : 1;
        const ub = isCurrent(b.name, current) ? 0 : 1;
        return ua - ub;
    });
    if (!shown.length) {
        gridEl.appendChild(el("div", "sc-emb-empty", MSG.noMatch));
        return;
    }
    for (const item of shown) gridEl.appendChild(buildCard(item, current));
}

function updateCount() {
    if (!countEl) return;
    const items = itemsCache.get(String(pickerOpts?.family || ""));
    if (!items) {
        countEl.textContent = "…";
        return;
    }
    const withPreview = items.filter((i) => i.hasPreview).length;
    const tally = {};
    for (const item of items) {
        const state = item.compat?.state;
        if (state) tally[state] = (tally[state] || 0) + 1;
    }
    const parts = [];
    if (tally.ok) parts.push(`${tally.ok} 兼容`);
    if (tally.partial) parts.push(`${tally.partial} 半兼容`);
    if (tally.incompatible) parts.push(`${tally.incompatible} 不兼容`);
    if (tally.missing) parts.push(`${tally.missing} 未安装`);
    if (tally.unknown) parts.push(`${tally.unknown} 未知`);
    countEl.textContent = `${items.length} 个 · 有图 ${withPreview}`
        + (parts.length ? ` · ${parts.join(" / ")}` : "");
}

function applyCellWidth() {
    if (gridEl) gridEl.style.setProperty("--sc-emb-cell", `${cellWidth}px`);
}

/** Insert one embedding through the caller's handler. Returns true on success. */
function pickCard(item, close) {
    if (!pickerOpts) return false;
    const opts = pickerOpts;
    const before = String(opts.getText?.() || "");
    if (typeof opts.onPick !== "function") {
        setStatus(MSG.noTarget, false);
        return false;
    }
    if (opts.onPick(item.name) === false) {
        setStatus(MSG.noTarget, false);
        return false;
    }
    const after = String(opts.getText?.() || "");
    undoStack.push({ opts, before, after });
    if (undoStack.length > 25) undoStack.shift();
    updateUndo();
    flashName = item.name;
    setStatus(`${MSG.picked} ${EMBEDDING_PREFIX}${item.name}`, true);
    renderGrid();
    if (close) closeEmbeddingPicker();
    return true;
}

function undoLastInsertion() {
    while (undoStack.length) {
        const record = undoStack.pop();
        const recordOpts = record?.opts;
        const current = String(recordOpts?.getText?.() || "");
        if (current !== record.after) {
            setStatus(MSG.undoBlocked, false);
            updateUndo();
            return false;
        }
        recordOpts?.setText?.(record.before);
        setStatus(MSG.undoDone, true);
        updateUndo();
        renderGrid();
        return true;
    }
    setStatus(MSG.undoEmpty, false);
    updateUndo();
    return false;
}

function buildPicker() {
    if (pickerEl) return;

    pickerEl = el("div", "sc-emb-backdrop");
    pickerEl.addEventListener("pointerdown", (e) => {
        if (e.target === pickerEl) closeEmbeddingPicker();
    });

    const modal = el("div", "sc-emb-modal");
    // Esc inside the picker closes the picker only (the prompt dialog behind it
    // answers the same key at document level - see PromptDialog.onKey).
    modal.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Escape") {
            e.preventDefault();
            closeEmbeddingPicker();
        }
    });

    const head = el("div", "sc-emb-head");
    countEl = el("div", "sc-emb-count", "…");

    searchEl = document.createElement("input");
    searchEl.className = "sc-emb-search";
    searchEl.type = "text";
    searchEl.placeholder = MSG.search;
    searchEl.addEventListener("input", renderGrid);

    const sizeWrap = el("div", "sc-emb-size");
    sizeWrap.appendChild(el("span", null, MSG.size));
    cellInput = document.createElement("input");
    cellInput.type = "range";
    cellInput.min = String(CELL_MIN);
    cellInput.max = String(CELL_MAX);
    cellInput.step = String(CELL_STEP);
    cellWidth = clamp(Number(readStore(STORE_CELL, CELL_DEFAULT)) || CELL_DEFAULT, CELL_MIN, CELL_MAX);
    cellInput.value = String(cellWidth);
    cellInput.addEventListener("input", () => {
        cellWidth = clamp(Number(cellInput.value) || CELL_DEFAULT, CELL_MIN, CELL_MAX);
        applyCellWidth();
        writeStore(STORE_CELL, cellWidth);
    });
    sizeWrap.appendChild(cellInput);

    const refresh = el("button", "sc-emb-btn", MSG.refresh);
    refresh.type = "button";
    refresh.title = "重新读取 models/embeddings";
    refresh.addEventListener("click", async () => {
        const family = String(pickerOpts?.family || "");
        itemsCache.delete(family);
        familyMeta.delete(family);
        await loadItems(family, true);
        updateCount();
        renderWhere();
        renderGrid();
    });

    const closeBtn = el("button", "sc-emb-btn sc-emb-close", "\u2715");
    closeBtn.type = "button";
    closeBtn.title = MSG.close;
    closeBtn.addEventListener("click", () => closeEmbeddingPicker());

    head.append(el("div", "sc-emb-title", MSG.title), countEl, searchEl, sizeWrap,
        el("div", "sc-emb-spacer"), refresh, closeBtn);

    // ---- subtitle: where the pick goes + result line ----
    const subtitle = el("div", "sc-emb-subtitle");
    whereEl = el("span", "sc-emb-where", "");
    statusEl = el("span", "sc-emb-status", "");
    subtitle.append(whereEl, el("div", "sc-emb-spacer"), statusEl);

    const body = el("div", "sc-emb-body");
    body.addEventListener("wheel", (e) => e.stopPropagation(), { passive: false });
    gridEl = el("div", "sc-emb-grid");
    body.appendChild(gridEl);

    const foot = el("div", "sc-emb-foot");
    foot.appendChild(el("span", "sc-emb-hint", MSG.hint));
    foot.appendChild(el("div", "sc-emb-spacer"));
    undoBtn = el("button", "sc-emb-btn", MSG.undo);
    undoBtn.type = "button";
    undoBtn.disabled = true;
    undoBtn.addEventListener("click", () => undoLastInsertion());
    const cancelBtn = el("button", "sc-emb-btn", MSG.close);
    cancelBtn.type = "button";
    cancelBtn.addEventListener("click", () => closeEmbeddingPicker());
    foot.append(undoBtn, cancelBtn);

    modal.append(head, subtitle, body, foot);
    pickerEl.appendChild(modal);
    document.body.appendChild(pickerEl);

    renderWhere();
    applyCellWidth();
}

/**
 * Open the embedding picker.
 *
 * @param {object} opts
 *   family   model preset used for the compat verdict (e.g. "pony")
 *   role     "positive" | "negative" - shown in the header, nothing else
 *   getText  () => current prompt text of the insertion target
 *   setText  (text) => write it back (used by 撤销插入)
 *   onPick   (name) => insert `embedding:name`; return false to report failure
 */
export function openEmbeddingPicker(opts = {}) {
    closeEmbeddingPicker();
    pickerOpts = {
        family: opts.family || "",
        role: opts.role === "negative" ? "negative" : "positive",
        getText: typeof opts.getText === "function" ? opts.getText : null,
        setText: typeof opts.setText === "function" ? opts.setText : null,
        onPick: typeof opts.onPick === "function" ? opts.onPick : null,
    };
    undoStack.length = 0;
    flashName = "";
    buildPicker();
    pickerEl.classList.add("sc-emb-open");
    updateUndo();
    renderWhere();
    setStatus("");
    updateCount();
    renderGrid();
    loadItems(pickerOpts.family, false).then(() => {
        if (!pickerOpts) return;
        updateCount();
        renderWhere();
        renderGrid();
    });
    setTimeout(() => searchEl?.focus?.(), 0);
}

/**
 * Re-judge the open list against another base family, without closing it.
 *
 * The dialog re-detects the base model every time its button is clicked (a
 * checkpoint switch is a widget change, which fires no connection callback), so
 * this is how the badges follow the model the user just selected.
 */
export async function setEmbeddingFamily(family = "") {
    if (!pickerOpts) return;
    const key = String(family || "");
    if (key === String(pickerOpts.family || "")) return;
    pickerOpts.family = key;
    renderWhere();
    renderGrid();
    await loadItems(key, false);
    if (!pickerOpts || String(pickerOpts.family || "") !== key) return;
    updateCount();
    renderWhere();
    renderGrid();
}

export function closeEmbeddingPicker() {
    pickerOpts = null;
    if (pickerEl) pickerEl.classList.remove("sc-emb-open");
}

export function isEmbeddingPickerOpen() {
    return !!pickerOpts;
}

/* ------------------------------------------------------------------ *
 * Global listeners
 * ------------------------------------------------------------------ */

function bindGlobalListeners() {
    document.addEventListener(
        "input",
        (e) => {
            if (e.isComposing) return;
            const box = e.target;
            if (!isPromptBox(box)) return;
            onPromptInput(box);
        },
        true
    );

    document.addEventListener(
        "compositionend",
        (e) => {
            if (isPromptBox(e.target)) onPromptInput(e.target);
        },
        true
    );

    // Keys are only intercepted while the suggestion list is visible.
    document.addEventListener(
        "keydown",
        (e) => {
            if (!popupState || e.target !== popupState.box) return;
            const n = popupState.matches.length;
            switch (e.key) {
                case "ArrowDown":
                    e.preventDefault();
                    e.stopPropagation();
                    popupState.index = (popupState.index + 1) % n;
                    renderPopup();
                    break;
                case "ArrowUp":
                    e.preventDefault();
                    e.stopPropagation();
                    popupState.index = (popupState.index - 1 + n) % n;
                    renderPopup();
                    break;
                case "Enter":
                case "Tab":
                    e.preventDefault();
                    e.stopPropagation();
                    acceptCompletion();
                    break;
                case "Escape":
                    e.preventDefault();
                    e.stopPropagation();
                    closePopup();
                    break;
                default:
                    break;
            }
        },
        true
    );

    window.addEventListener("resize", closePopup, true);
    window.addEventListener("blur", closePopup, true);
    document.addEventListener("wheel", closePopup, true);

    document.addEventListener(
        "pointerdown",
        (e) => {
            if (popupEl && popupEl.contains(e.target)) return;
            closePopup();
        },
        true
    );
}

/* ------------------------------------------------------------------ *
 * Styles
 * ------------------------------------------------------------------ */

const CSS = `
.sc-emb-popup {
    position: fixed;
    z-index: 10002;
    min-width: 200px;
    max-height: 260px;
    overflow-y: auto;
    display: none;
    background: #17171c;
    color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.2);
    border-radius: 8px;
    box-shadow: 0 12px 32px rgba(0,0,0,.66);
    font: 12px/1.5 system-ui, "Microsoft YaHei", sans-serif;
    padding: 3px;
}
.sc-emb-popup-row {
    padding: 4px 8px;
    border-radius: 5px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #cfcfd6;
}
.sc-emb-popup-row:hover { background: rgba(255,255,255,.08); }
.sc-emb-popup-row.sc-emb-active { background: #d08a2b; color: #241a08; font-weight: 700; }

/* ---- picker: a sub-dialog of 选择提示词 (z-index above .sc-overlay 13000) ---- */
.sc-emb-backdrop {
    position: fixed; inset: 0; z-index: 13100;
    background: rgba(0,0,0,.6);
    display: none; align-items: center; justify-content: center;
    transform: none !important;
    font: 13px/1.45 system-ui, "Microsoft YaHei", sans-serif;
}
.sc-emb-backdrop.sc-emb-open { display: flex; }
.sc-emb-modal {
    background: #17171c; color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.16); border-radius: 12px;
    width: min(900px, 92vw); height: min(76vh, 720px);
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,.7);
}
.sc-emb-head {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 12px 16px; background: #1e1e24;
    border-bottom: 1px solid rgba(255,255,255,.09);
}
.sc-emb-title { font-size: 15px; font-weight: 700; color: #4a9eff; }
.sc-emb-count { color: #8a8a95; font-size: 11px; }
.sc-emb-spacer { flex: 1 1 auto; }
.sc-emb-search {
    flex: 1 1 160px; min-width: 120px; background: #101014; color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.18); border-radius: 7px;
    padding: 6px 10px; font: inherit; outline: none;
}
.sc-emb-search:focus { border-color: #4a9eff; }
.sc-emb-size { display: flex; align-items: center; gap: 6px; color: #8a8a95; font-size: 11px; }
.sc-emb-size input { width: 90px; accent-color: #4a9eff; }
.sc-emb-btn {
    background: #26262e; border: 1px solid rgba(255,255,255,.16);
    border-radius: 7px; color: #d8d8dd; cursor: pointer;
    padding: 5px 12px; font: inherit;
}
.sc-emb-btn:hover { background: #33333d; color: #fff; }
.sc-emb-btn[disabled] { opacity: .5; cursor: default; }
.sc-emb-subtitle {
    flex: 0 0 auto; padding: 7px 16px; background: #141419;
    border-bottom: 1px solid rgba(255,255,255,.06);
    color: #9a9aa6; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.sc-emb-status { color: #6f6f7c; font-size: 11px; }
.sc-emb-status.sc-emb-status-bad { color: #ff9c95; }
.sc-emb-body { flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; padding: 14px; }
.sc-emb-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--sc-emb-cell, 124px), 1fr));
    gap: 10px;
}
.sc-emb-empty { color: #7a7a86; padding: 24px; text-align: center; }
.sc-emb-card {
    background: #202027; border: 1px solid rgba(255,255,255,.09);
    border-radius: 9px; cursor: pointer; overflow: hidden;
    display: flex; flex-direction: column; position: relative;
}
.sc-emb-card:hover { border-color: #4a9eff; background: #262630; }
.sc-emb-thumb {
    width: 100%; aspect-ratio: 1 / 1; display: block;
    background: #0e0e12; object-fit: contain;
}
.sc-emb-thumb-img {
    width: 100%; aspect-ratio: 1 / 1; object-fit: contain;
    display: block; background: #0e0e12;
}
.sc-emb-thumb-empty {
    display: flex; align-items: center; justify-content: center;
    color: #5a5a66; font-size: 22px; font-weight: 700;
}
.sc-emb-card-name {
    padding: 5px 7px; font-size: 11px; color: #c8c8d0;
    word-break: break-all; line-height: 1.25;
}
/* 兼容徽标（与「选择提示词」弹窗同源） */
.sc-emb-badge {
    margin: 0 7px 6px; font-size: 10px; font-weight: 700;
    padding: 1px 7px; border-radius: 999px; align-self: flex-start;
    background: #2b2b33; color: #a9a9b4; border: 1px solid rgba(255,255,255,.16);
}
.sc-emb-badge-ok { background: #1d2739; color: #9fc6ff; border-color: #3d8bfd; }
.sc-emb-badge-partial { background: #3a2f1c; color: #ffc978; border-color: #f0a132; }
.sc-emb-badge-incompatible { background: #3a1f22; color: #ff9c95; border-color: #ff5f56; }
.sc-emb-badge-missing { background: #2f2b1c; color: #e8d08a; border-color: #c9a227; }
/* 颜色语义抄 LoRA 模型弹窗：红 = 不兼容、蓝 = 兼容、黄 = 半兼容
   （SDXL 上的 768 维 SD1.5 词嵌入：CLIP-L 吃、CLIP-G 忽略）、绿 = 当前使用（绿优先） */
.sc-emb-card.sc-emb-cf-red { border-color: #ff5f56; box-shadow: 0 0 0 2px #ff5f56 inset; background: #3a1f22; }
.sc-emb-card.sc-emb-cf-blue { border-color: #3d8bfd; box-shadow: 0 0 0 2px #3d8bfd inset; background: #1d2739; }
.sc-emb-card.sc-emb-cf-amber { border-color: #f0a132; box-shadow: 0 0 0 2px #f0a132 inset; background: #352a18; }
.sc-emb-card.sc-emb-cf-red:hover { border-color: #ff8b84; }
.sc-emb-card.sc-emb-cf-blue:hover { border-color: #6ba8ff; }
.sc-emb-card.sc-emb-cf-amber:hover { border-color: #ffc978; }
.sc-emb-card.sc-emb-current { border-color: #5bc27e; box-shadow: 0 0 0 2px #5bc27e inset; background: #24322a; }
.sc-emb-now {
    position: absolute; top: 5px; left: 5px; z-index: 2;
    background: #5bc27e; color: #08210f; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 999px; box-shadow: 0 1px 4px rgba(0,0,0,.5);
}
.sc-emb-card-copy {
    margin: 0 7px 7px; align-self: flex-start;
    background: #26262e; border: 1px solid rgba(255,255,255,.16);
    border-radius: 6px; color: #b8b8c2; cursor: pointer;
    padding: 3px 9px; font: 11px inherit;
}
.sc-emb-card-copy:hover { background: #33333d; color: #fff; }
.sc-emb-card-tick { position: absolute; top: 5px; right: 5px; color: #5bc27e; font-weight: 700; opacity: 0; }
.sc-emb-card.sc-emb-picked .sc-emb-card-tick { opacity: 1; }
.sc-emb-card.sc-emb-picked { border-color: #5bc27e; }
.sc-emb-foot {
    flex: 0 0 auto; padding: 8px 16px; background: #141419;
    border-top: 1px solid rgba(255,255,255,.08);
    color: #6f6f7c; font-size: 11px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
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
 * Extension entry point
 * ------------------------------------------------------------------ */

app.registerExtension({
    name: EXT_NAME,

    async setup() {
        injectCss();
        bindGlobalListeners();
        await loadItems();
        console.log(`[${EXT_NAME}] ready (${embeddings.length} embeddings, 打字补全 + 选择弹窗)`);
    },
});

console.log(`[${EXT_NAME}] loaded`);
