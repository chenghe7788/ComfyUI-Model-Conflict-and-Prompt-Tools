/**
 * Model conflict colouring for the model picker modal
 * ===================================================
 * Companion module of model_image_picker.js.  It answers, for every card in the
 * picker, whether that model clashes with the architecture the rest of the
 * workflow is built on:
 *
 *   red    -> conflict (different architecture family)
 *   blue   -> compatible
 *   green  -> currently in use (already existed, unaffected)
 *   no colour -> architecture could not be determined, so nothing is claimed
 *
 * Everything architecture related lives on the Python side (model_conflict.py).
 * This module only has to
 *   1. know which model names belong to which model folder (so it can read the
 *      graph's model picks without asking the server for the workflow),
 *   2. POST that pick list together with the names currently displayed,
 *   3. paint the cards with the answer.
 *
 * The node -> widget table below is the single source of truth for both the
 * "open picker" buttons and the graph scan, so adding a model kind in one place
 * is enough.
 */

import { app } from "../../scripts/app.js";

const API_INDEX = "/modelconflict/index";
const API_CHECK = "/modelconflict/check";

/** Colour identity of the three states. */
export const COLOURS = {
    conflict: "#ff5f56",
    ok: "#3d8bfd",
    current: "#5bc27e",
};

/**
 * node type -> [model kind, widget name].
 * The picker attaches a button for these, and the graph scan uses the same
 * table to find the workflow's models.
 */
export const NODE_FIELDS = {
    CheckpointLoaderSimple: ["checkpoints", "ckpt_name"],
    CheckpointLoader: ["checkpoints", "ckpt_name"],
    LoraLoader: ["loras", "lora_name"],
    LoraLoaderModelOnly: ["loras", "lora_name"],
    VAELoader: ["vae", "vae_name"],
    ControlNetLoader: ["controlnet", "control_net_name"],
    UNETLoader: ["diffusion_models", "unet_name"],
    CLIPLoader: ["text_encoders", "clip_name"],
    DualCLIPLoader: ["text_encoders", "clip_name1"],
    UpscaleModelLoader: ["upscale_models", "model_name"],
    SAMLoader: ["sams", "model_name"],
    UltralyticsDetectorProvider: ["ultralytics", "model_name"],
};

/** Fallback labels when the backend index is unavailable. */
export const KIND_LABELS = {
    checkpoints: "\u5927\u6a21\u578b",
    diffusion_models: "UNET",
    loras: "LoRA",
    vae: "VAE",
    embeddings: "\u8bcd\u5d4c\u5165",
    controlnet: "ControlNet",
    text_encoders: "\u6587\u672c\u7f16\u7801\u5668",
    upscale_models: "\u653e\u5927\u6a21\u578b",
    sams: "SAM",
    ultralytics: "\u68c0\u6d4b\u6a21\u578b",
};

/** Human wording for the model kind a baseline came from. */
const SOURCE_LABEL = {
    checkpoints: "\u5927\u6a21\u578b",
    diffusion_models: "UNET",
    loras: "LoRA",
    vae: "VAE",
    embeddings: "\u8bcd\u5d4c\u5165",
    controlnet: "ControlNet",
    text_encoders: "\u6587\u672c\u7f16\u7801\u5668",
};

/* ------------------------------------------------------------------ *
 * Backend index: model name -> kind
 * ------------------------------------------------------------------ */

const indexState = {
    ready: false,
    promise: null,
    /** normalised name -> kind (the first, most specific kind wins) */
    names: new Map(),
    /** normalised basename -> kind, for names quoted without their subfolder */
    basenames: new Map(),
    labels: {},
    roles: {},
    kinds: {},
};

/**
 * Smart punctuation (Word, some editors, chat apps) silently replaces ASCII
 * hyphens with U+2011 and friends.  ComfyUI cannot resolve such a name, and the
 * workflow files shipped with this machine really do contain them, so lookups
 * normalise them away before comparing.
 */
const SMART_PUNCT = /[\u2010-\u2015\u2212\ufe63\uff0d]/g;
const ZERO_WIDTH = /[\u200b-\u200d\ufeff]/g;

function normalize(name) {
    return String(name == null ? "" : name)
        .replace(SMART_PUNCT, "-")
        .replace(ZERO_WIDTH, "")
        .replace(/\\/g, "/")
        .trim()
        .toLowerCase();
}

/**
 * Kinds are ranked so that a name existing in several folders resolves to the
 * most meaningful one (a checkpoint beats a LoRA with the same file name).
 */
const KIND_RANK = [
    "checkpoints", "diffusion_models", "loras", "controlnet",
    "vae", "text_encoders", "embeddings", "upscale_models",
    "sams", "ultralytics",
];

export function ensureIndex() {
    if (indexState.ready) return Promise.resolve(indexState);
    if (indexState.promise) return indexState.promise;

    indexState.promise = (async () => {
        try {
            const res = await fetch(API_INDEX);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            indexState.labels = data.labels || {};
            indexState.roles = data.roles || {};
            indexState.kinds = data.kinds || {};

            const rank = new Map(KIND_RANK.map((k, i) => [k, i]));
            const better = (prev, kind) => {
                if (!prev) return kind;
                const a = rank.has(prev) ? rank.get(prev) : 99;
                const b = rank.has(kind) ? rank.get(kind) : 99;
                return b < a ? kind : prev;
            };
            for (const [kind, names] of Object.entries(indexState.kinds)) {
                for (const name of names || []) {
                    const key = normalize(name);
                    indexState.names.set(key, better(indexState.names.get(key), kind));
                    const base = key.split("/").pop();
                    if (base) {
                        indexState.basenames.set(base,
                            better(indexState.basenames.get(base), kind));
                    }
                }
            }
            indexState.ready = true;
            console.log(`[ModelConflict] indexed ${indexState.names.size} model names ` +
                `(${indexState.basenames.size} with a subfolder)`);
        } catch (err) {
            console.warn("[ModelConflict] index unavailable:", err);
        }
        return indexState;
    })();

    return indexState.promise;
}

/** Which model folder a picker entry belongs to, or "" when unknown. */
export function kindOf(name) {
    const key = normalize(name);
    if (indexState.names.has(key)) return indexState.names.get(key);
    // names are sometimes quoted with the other separator
    const alt = key.includes("/") ? key.replace(/\//g, "\\") : key.replace(/\\/g, "/");
    if (indexState.names.has(alt)) return indexState.names.get(alt);
    // ... or without their subfolder (e.g. "vae-ft-mse-840000-ema-pruned.safetensors")
    const base = key.split("/").pop();
    if (base && indexState.basenames.has(base)) return indexState.basenames.get(base);
    // textual inversions are referenced without a file extension
    if (!base.includes(".")) {
        for (const ext of [".safetensors", ".pt", ".ckpt"]) {
            if (indexState.basenames.has(base + ext)) return indexState.basenames.get(base + ext);
            if (indexState.names.has(base + ext)) return indexState.names.get(base + ext);
        }
    }
    return "";
}

/** Kind lists straight from the backend (used to index context menus). */
export function indexKinds() {
    return ensureIndex().then((state) => state.kinds || {});
}

export function labelFor(kind) {
    return indexState.labels[kind] || KIND_LABELS[kind] || kind;
}

/* ------------------------------------------------------------------ *
 * Reading the workflow's models
 * ------------------------------------------------------------------ */

function widgetText(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "object" && typeof value.content === "string") return value.content;
    return "";
}

const SENTINELS = new Set(["none", "null", "undefined", "n/a", "", "\u65e0", "\u7a7a"]);

const EMBEDDING_RE = /embedding:([^,\s)\]\n]+)/g;

/**
 * Every model the workflow is currently wired up with, grouped by kind.
 *
 * The widget value is classified through the backend index instead of through
 * the node type, which is what makes this work for nodes this pack knows
 * nothing about - a LoRA stack with ten slots, an Impact Pack detector pair, a
 * community loader - as long as the value is a real model name.
 */
export function graphPicks() {
    const picks = {};
    const add = (kind, value) => {
        if (!kind || !value) return;
        const arr = picks[kind] || (picks[kind] = []);
        if (arr.length < 80 && !arr.includes(value)) arr.push(value);
    };

    const nodes = app?.graph?._nodes || [];
    for (const node of nodes) {
        const widgets = node?.widgets || [];
        for (const widget of widgets) {
            const text = widgetText(widget?.value);
            if (!text) continue;

            const kind = kindOf(text);
            if (kind && !SENTINELS.has(text.trim().toLowerCase())) add(kind, text);

            // textual inversions are referenced inside prompt text
            if (text.includes("embedding:")) {
                EMBEDDING_RE.lastIndex = 0;
                let m;
                while ((m = EMBEDDING_RE.exec(text)) !== null) {
                    add("embeddings", m[1].replace(/[.\u3002\uff0c]+$/, ""));
                }
            }
        }
    }
    return picks;
}

/* ------------------------------------------------------------------ *
 * Asking the backend
 * ------------------------------------------------------------------ */

/**
 * Annotate `names` (the entries the picker is showing) against the workflow.
 * Returns the backend payload, or null when the check could not run - in which
 * case the picker simply shows no colours.
 */
export async function statusFor(kind, names) {
    if (!kind || !names || !names.length) return null;
    await ensureIndex();
    try {
        const res = await fetch(API_CHECK, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind, names, picks: graphPicks() }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        return data && data.items ? data : null;
    } catch (err) {
        console.warn("[ModelConflict] check failed:", err);
        return null;
    }
}

function infoFor(status, name) {
    if (!status?.items) return null;
    if (status.items[name]) return status.items[name];
    const alt = String(name).replace(/\//g, "\\");
    return status.items[alt] || null;
}

/* ------------------------------------------------------------------ *
 * Painting
 * ------------------------------------------------------------------ */

/**
 * Add the conflict/ok colouring to one card.  The "currently in use" card keeps
 * its green styling: the CSS excludes .mip-sel from the red/blue rules.
 */
export function applyCardState(card, status, name) {
    const info = infoFor(status, name);
    if (!card || !info) return;

    if (info.state === "conflict") card.classList.add("mip-cf-red");
    else if (info.state === "ok") card.classList.add("mip-cf-blue");

    card.dataset.mcState = info.state;
    card.title = `${name}\n${info.label || ""}${info.why ? " \u00b7 " + info.why : ""}`;

    if (info.short && info.short !== "?" && info.state !== "unknown") {
        const badge = document.createElement("div");
        badge.className = "mip-arch";
        badge.textContent = info.short;
        card.appendChild(badge);
    }
}

function chip(text, colour) {
    const span = document.createElement("span");
    span.className = "mip-chip";
    span.textContent = text;
    if (colour) {
        span.style.background = colour;
        span.style.color = "#0d0d10";
    }
    return span;
}

function basename(name) {
    const parts = String(name).replace(/\\/g, "/").split("/");
    return parts[parts.length - 1] || String(name);
}

/**
 * The baseline + tally line shown under the header:
 *
 *   基准: SD 1.5（大模型 majicmixRealistic_v7.safetensors）  [46 冲突] [2 兼容]
 *
 * For the base-model picker there is no single baseline (the candidates *are*
 * base models), so it lists what the wired-up models ask for instead.
 */
export function buildLegend(status) {
    const wrap = document.createElement("span");
    wrap.className = "mip-legend";
    if (!status) return wrap;

    const ref = status.reference;
    const shorts = {};
    for (const [fam, slot] of Object.entries(status.graph || {})) {
        shorts[fam] = slot.short || fam;
    }

    let text = "";
    if (ref && ref.mode === "base") {
        const fams = Object.entries(ref.families || {})
            .sort((a, b) => b[1] - a[1])
            .map(([fam, n]) => `${shorts[fam] || fam}\u00d7${n}`)
            .join(" \u00b7 ");
        text = `\u5de5\u4f5c\u6d41\u9700\u8981: ${fams}`;
    } else if (ref) {
        const src = SOURCE_LABEL[ref.source_kind] || ref.source_kind;
        text = `\u57fa\u51c6: ${ref.label}\uff08${src} ${basename(ref.source_name || "")}\uff09`;
    } else {
        text = "\u5de5\u4f5c\u6d41\u91cc\u6ca1\u6709\u53ef\u53c2\u7167\u7684\u6a21\u578b\uff0c\u6682\u4e0d\u7740\u8272";
    }

    const dot = document.createElement("span");
    dot.className = "mip-dot";
    wrap.append(dot, document.createTextNode(text));

    const counts = status.counts || {};
    const tally = document.createElement("span");
    tally.className = "mip-tally";
    tally.append(
        chip(`${counts.conflict || 0} \u51b2\u7a81`, COLOURS.conflict),
        chip(`${counts.ok || 0} \u517c\u5bb9`, COLOURS.ok),
    );
    if (counts.unknown) {
        tally.append(chip(`${counts.unknown} \u672a\u77e5`, null));
    }
    wrap.append(tally);

    // When the graph itself already mixes families it is worth saying so.
    const families = Object.entries(status.graph || {});
    if (ref && ref.mode !== "base" && families.length > 1) {
        const hist = document.createElement("span");
        hist.className = "mip-hist";
        hist.textContent = "\u56fe\u5185: " + families
            .sort((a, b) => b[1].count - a[1].count)
            .map(([, slot]) => `${slot.short}\u00d7${slot.count}`)
            .join(" \u00b7 ");
        wrap.append(hist);
    }

    return wrap;
}

console.log("[ModelConflict] module loaded");
