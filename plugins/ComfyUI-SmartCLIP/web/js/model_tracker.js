/**
 * Model tracker for SmartCLIP
 * ===========================
 * Answers "which architecture is this node's CLIP?" from two sources:
 *
 *   1. runtime truth  - the ui payload the node sends after it executes
 *                       (node.onExecuted -> output.smart_clip[0]).  Authoritative
 *                       for the base family, but only available *after* the first
 *                       run.
 *   2. graph trace    - walking the CLIP input wire upstream to the loader and
 *                       reading its model-file widget.  Available immediately,
 *                       and it is the only source that can see the checkpoint
 *                       *name*, hence the flavour (Pony / Illustrious / Krea 2)
 *                       and the right preset set.
 *
 * The merged result is cached on node.properties.smart_clip so it survives a
 * page refresh with the workflow.
 *
 * Everything here is defensive: a graph that does not look like this ComfyUI's
 * (or a node type we have never seen) must degrade to "unknown", never throw.
 *
 * Verified against the frontend actually served by this install
 * (comfyui-frontend-package 1.41.21):
 *   - LiteGraph keeps links in `graph._links`, a Map.  `graph.links` is declared
 *     but never assigned in this fork, so `graph.links[id]` (as the draft this
 *     replaces used) is `undefined[id]` -> TypeError, and the role detection
 *     never runs.
 *   - `node.getOutputNodes(slot)` is the public traversal helper.
 *   - `node.properties` is serialised into the workflow; `getProperty` is not
 *     present in this fork, so properties are read directly.
 */

import { app } from "../../scripts/app.js";

const API_DETECT = "/smart_clip/detect";

/** Loader node types whose widget names hold a model file name. */
export const LOADER_FIELDS = {
    CheckpointLoaderSimple: ["ckpt_name", "checkpoints"],
    CheckpointLoader: ["ckpt_name", "checkpoints"],
    UNETLoader: ["unet_name", "diffusion_models"],
    UnetLoaderGGUF: ["unet_name", "diffusion_models"],
    CLIPLoader: ["clip_name", "text_encoders"],
    DualCLIPLoader: ["clip_name1", "text_encoders"],
    CLIPVisionLoader: ["clip_name", "clip_vision"],
};

/** Instant, offline flavour hint from a file name (server refines it later). */
const NAME_HINTS = [
    ["pony", /pony|pdxl|_pxl/i],
    ["illustrious", /illustrious|noob|ilff|nijijourney|hassaku/i],
    ["krea2", /krea/i],
    ["flux", /flux/i],
    ["sd3", /sd3|stable[-_ ]?diffusion[-_ ]?3/i],
    ["sd15", /sd[-_ ]?1[._]?5|sd15|v1[-_ ]?5/i],
    ["sdxl", /sdxl|xl_base|[-_]xl[-_]|xl_?v?\d/i],
];

export function hintFromName(name) {
    const text = String(name || "").toLowerCase();
    for (const [family, pattern] of NAME_HINTS) {
        if (pattern.test(text)) return family;
    }
    return "";
}

/* ------------------------------------------------------------------ *
 * Link access that works on both LiteGraph flavours
 * ------------------------------------------------------------------ */

function linkById(graph, id) {
    if (!graph || id == null) return null;
    try {
        const links = graph._links;
        if (links && typeof links.get === "function") {
            const hit = links.get(id);
            if (hit) return hit;
        }
        if (links && typeof links === "object" && links[id]) return links[id];
        if (graph.links && graph.links[id]) return graph.links[id];
    } catch (err) {
        /* fall through */
    }
    return null;
}

function nodeById(graph, id) {
    try {
        return graph?.getNodeById?.(id) || graph?._nodes_by_id?.[id] || null;
    } catch (err) {
        return null;
    }
}

/**
 * Nodes reached by one output slot, without relying on graph.links.
 * Cycle-safe: LiteGraph can hold a loop even though execution would reject it.
 */
export function outputTargets(node, slot = 0) {
    const graph = node?.graph || app?.graph;
    const out = [];
    const output = node?.outputs?.[slot];
    const links = output?.links || [];
    for (const id of links) {
        const link = linkById(graph, id);
        if (!link) continue;
        const target = nodeById(graph, link.target_id);
        if (target) out.push({ node: target, slot: link.target_slot, link });
    }
    return out;
}

/** Nodes feeding one input slot. */
export function inputSources(node, slot) {
    const graph = node?.graph || app?.graph;
    const input = node?.inputs?.[slot];
    if (!input) return [];
    const ids = [];
    if (input.link != null) ids.push(input.link);
    for (const id of input.links || []) if (id != null && !ids.includes(id)) ids.push(id);
    const out = [];
    for (const id of ids) {
        const link = linkById(graph, id);
        if (!link) continue;
        const source = nodeById(graph, link.origin_id);
        if (source) out.push({ node: source, slot: link.origin_slot, link });
    }
    return out;
}

/** Index of the CLIP input on a node, or -1. */
export function clipInputIndex(node) {
    const inputs = node?.inputs || [];
    for (let i = 0; i < inputs.length; i++) {
        const type = inputs[i]?.type;
        if (type === "CLIP" || (Array.isArray(type) && type.includes("CLIP"))) return i;
    }
    return -1;
}

/* ------------------------------------------------------------------ *
 * Graph trace
 * ------------------------------------------------------------------ */

const MAX_VISITED = 64;
const MAX_DEPTH = 24;

/**
 * Walk upstream from a node's CLIP input and collect model-file hints.
 * -> {names: [{name, kind, node, field}], visited, truncated}
 */
export function traceUpstream(node, startSlot = null) {
    const names = [];
    const visited = new Set();
    let truncated = false;

    let frontier = [];
    const slot = startSlot == null ? clipInputIndex(node) : startSlot;
    for (const src of inputSources(node, slot)) frontier.push({ node: src.node, depth: 1 });

    while (frontier.length) {
        if (visited.size >= MAX_VISITED) {
            truncated = true;
            break;
        }
        const { node: current, depth } = frontier.shift();
        if (!current || depth > MAX_DEPTH) {
            truncated = true;
            continue;
        }
        const key = current.id ?? current.type;
        if (visited.has(key)) continue;      // cycle guard
        visited.add(key);

        // model-file widgets on this node
        const fields = LOADER_FIELDS[current.type];
        if (fields && current.widgets) {
            const [field, kind] = fields;
            const widget = current.widgets.find((w) => w?.name === field);
            const value = readWidgetText(widget);
            if (value && !isSentinel(value)) {
                names.push({ name: value, kind, node: current, field });
            }
            // a loader is a leaf for our purposes
            continue;
        }

        // otherwise keep following every CLIP-ish input
        const inputs = current.inputs || [];
        for (let i = 0; i < inputs.length; i++) {
            const type = inputs[i]?.type;
            const isClip = type === "CLIP" || (Array.isArray(type) && type.includes("CLIP"));
            if (!isClip && current.type !== "SmartCLIPTextEncode") continue;
            for (const src of inputSources(current, i)) {
                frontier.push({ node: src.node, depth: depth + 1 });
            }
        }
    }

    return { names, visited: visited.size, truncated };
}

function readWidgetText(widget) {
    const raw = widget?.value;
    if (raw == null) return "";
    if (typeof raw === "string") return raw;
    if (typeof raw === "object" && typeof raw.content === "string") return raw.content;
    return String(raw);
}

const SENTINEL_RE = /^(none|null|undefined|n\/a|无|空)$/i;
function isSentinel(value) {
    return !value || SENTINEL_RE.test(String(value).trim());
}

/* ------------------------------------------------------------------ *
 * Whole-graph fallback
 * ------------------------------------------------------------------ */

/** A checkpoint is the base model; a bare UNET or CLIP loader is only a hint. */
const LOADER_KIND_RANK = { checkpoints: 0, diffusion_models: 1, text_encoders: 2 };

function loaderRank(kind) {
    const rank = LOADER_KIND_RANK[kind];
    return rank == null ? 9 : rank;
}

/**
 * Every model file the *whole* graph names, checkpoints first.
 *
 * ``traceUpstream`` is the exact answer ("this node's CLIP comes from there"),
 * but it needs wires the frontend can walk.  A CLIP that runs through a
 * community LoRA stack, a page that loaded while ComfyUI was still starting, or
 * a stale cached bundle can leave it empty - and then the embedding picker has
 * no family to judge against and every entry degrades to "unknown".
 *
 * So when the trace finds nothing we still read the loader widgets themselves
 * (the same idea ComfyUI_ModelImagePicker uses to colour its context menu).
 * A workflow with two loaders is ranked, not guessed at.
 */
export function graphLoaderNames(graph = null) {
    const target = graph || app?.graph;
    const out = [];
    for (const node of target?._nodes || []) {
        const fields = LOADER_FIELDS[node?.comfyClass || node?.type];
        if (!fields) continue;
        const [field, kind] = fields;
        const widget = (node.widgets || []).find((w) => w?.name === field);
        const value = readWidgetText(widget);
        if (!value || isSentinel(value)) continue;
        out.push({ name: value, kind, node, field, via: "graph" });
    }
    out.sort((a, b) => loaderRank(a.kind) - loaderRank(b.kind));
    return out;
}

/* ------------------------------------------------------------------ *
 * Server-side refinement
 * ------------------------------------------------------------------ */

const detectCache = new Map();      // "kind::name" -> record

/** A page can load before ComfyUI's routes exist; one retry, once. */
const DETECT_RETRY_MS = 1000;

export async function detectOnServer(name, kind = "checkpoints", retry = false) {
    const key = `${kind}::${name}`;
    if (detectCache.has(key)) return detectCache.get(key);
    try {
        const url = `${API_DETECT}?kind=${encodeURIComponent(kind)}&names=${encodeURIComponent(name)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const item = data?.items?.[0] || null;
        if (item) detectCache.set(key, item);
        return item;
    } catch (err) {
        console.warn("[SmartCLIP] detect failed:", err);
        if (retry) {
            await new Promise((resolve) => setTimeout(resolve, DETECT_RETRY_MS));
            return detectOnServer(name, kind, false);
        }
        return null;
    }
}

/* ------------------------------------------------------------------ *
 * Public tracker
 * ------------------------------------------------------------------ */

export class ModelTracker {
    /** Attach the runtime hook + restore any cached state. */
    static init(node) {
        if (!node) return;
        if (!node.properties) node.properties = {};
        if (!node.properties.smart_clip) {
            node.properties.smart_clip = { family: "unknown", label: "", preset: "generic" };
        }

        const previous = node.onExecuted;
        node.onExecuted = function (output) {
            try {
                previous?.apply(this, arguments);
            } catch (err) {
                console.warn("[SmartCLIP] previous onExecuted failed:", err);
            }
            const payload = Array.isArray(output?.smart_clip)
                ? output.smart_clip[0]
                : output?.smart_clip;
            if (payload && typeof payload === "object") {
                ModelTracker.setRuntime(node, payload);
            }
        };
    }

    /** The node really executed: this is the authoritative answer. */
    static setRuntime(node, payload) {
        const state = ModelTracker.state(node);
        state.runtime = {
            family: payload.family || "unknown",
            label: payload.label || "",
            preset: payload.preset || "generic",
            score_tags: !!payload.score_tags,
            evidence: payload.evidence || "",
            note: payload.note || "",
            source: payload.source || "node",
            role: payload.role || "auto",
            category: payload.category || "",
            encoded_text: payload.raw_text ?? null,
            chars: payload.chars ?? null,
        };
        node.properties.smart_clip = state;
        ModelTracker.refreshUI(node);
    }

    /**
     * Pre-execution graph guess: walk the CLIP wire, fall back to the loader
     * widgets when the walk comes up empty, then let the server read the file
     * header.  Never blanks a verdict it already has.
     */
    static async refreshFromGraph(node) {
        const state = ModelTracker.state(node);
        const previous = state.graph || {};
        const trace = traceUpstream(node);
        let first = trace.names[0] || null;
        let via = "wire";

        if (!first) {
            // No walkable CLIP wire (a stack node in between, a node that is not
            // connected yet, a page that loaded before the graph was restored):
            // the loader widgets still say which checkpoint the workflow uses.
            const fallback = graphLoaderNames(node?.graph || app?.graph);
            if (fallback.length) {
                first = fallback[0];
                via = "graph";
            }
        }

        if (!first) {
            if (previous.name) {
                // Nothing to look at right now.  Keeping the last answer beats
                // blanking the dialog to "unknown" - an empty trace is not
                // evidence that the old verdict was wrong.
                state.graph = previous;
            } else {
                state.graph = {
                    names: [], name: "", kind: "", hint: "",
                    truncated: trace.truncated, visited: trace.visited, via: "none",
                };
                node.properties.smart_clip = state;
            }
            return state;
        }

        state.graph = {
            names: trace.names.length ? trace.names.map((n) => n.name) : [first.name],
            name: first.name,
            kind: first.kind,
            hint: hintFromName(first.name) || previous.hint || "",
            truncated: trace.truncated,
            visited: trace.visited,
            via,
            // Keep the previous server verdict visible until the new one lands.
            family: previous.family,
            label: previous.label,
            preset: previous.preset,
            score_tags: previous.score_tags,
            evidence: previous.evidence,
        };
        node.properties.smart_clip = state;
        ModelTracker.refreshUI(node);

        // refine with the server (reads the model header), then refresh again
        const item = await detectOnServer(first.name, first.kind, true);
        if (item) {
            state.graph = Object.assign(state.graph, {
                family: item.family,
                label: item.label,
                preset: item.preset,
                score_tags: !!item.score_tags,
                evidence: item.evidence,
                hint: item.hint || state.graph.hint,
            });
            node.properties.smart_clip = state;
            ModelTracker.refreshUI(node);
        }
        return state;
    }

    static state(node) {
        if (!node.properties) node.properties = {};
        const state = node.properties.smart_clip || {};
        return {
            runtime: state.runtime || null,
            graph: state.graph || null,
        };
    }

    /**
     * Merged view used by the dialog and the button label.
     * runtime family is authoritative; flavour hints upgrade the preset.
     */
    static getModel(node) {
        const state = ModelTracker.state(node);
        const runtime = state.runtime || {};
        const graph = state.graph || {};
        const family = runtime.family || graph.family || graph.hint || "unknown";
        const hint = graph.hint || "";

        let preset = runtime.preset || graph.preset || "";
        if (!preset || preset === "generic") {
            if (hint === "pony" || hint === "illustrious") preset = hint;
            else if (graph.preset) preset = graph.preset;
            else preset = "generic";
        } else if (family === "sdxl" && (hint === "pony" || hint === "illustrious")) {
            // a Pony/Illustrious checkpoint is SDXL structurally but wants its
            // own word list, so the flavour wins for preset selection
            preset = hint;
        }

        return {
            family,
            label: runtime.label || graph.label || "",
            preset,
            scoreTags: !!(runtime.score_tags || graph.score_tags),
            evidence: runtime.evidence || graph.evidence || "",
            note: runtime.note || "",
            source: runtime.family ? "node" : (graph.family ? "server" : (graph.hint ? "name" : "none")),
            role: runtime.role || "auto",
            name: graph.name || "",
            graphLabel: graph.label || "",
            runtimeSeen: !!runtime.family,
        };
    }

    /**
     * Show the detected model on the node's own button.
     *
     * The widget's rendered text is `label || localized_name || name`, so the
     * label can be updated without touching the widget *name* (which is how the
     * widget is found again - renaming it would break the next refresh).
     */
    static refreshUI(node) {
        try {
            const model = ModelTracker.getModel(node);
            const button = (node.widgets || []).find((w) => w?.name === "smart_clip_pick");
            if (!button) return;
            const role = ModelTracker.detectRole(node);
            const head = model.label || model.family !== "unknown"
                ? (model.label || model.family)
                : (model.graphLabel || "未识别");
            const where = model.runtimeSeen ? "" : (model.source === "server" ? " · 预判" : "");
            const text = `📝 选择提示词（${head}${where} · ${role === "negative" ? "负面" : role === "positive" ? "正面" : "?"}）`;
            button.label = text;
            const element = button.element || button.inputEl;
            if (element && typeof element.textContent === "string" && element.tagName) {
                element.textContent = text;
            }
            app.graph?.setDirtyCanvas(true, true);
        } catch (err) {
            console.warn("[SmartCLIP] refreshUI failed:", err);
        }
    }

    /** Which KSampler slot does this node feed? -> positive / negative / auto */
    static detectRole(node) {
        const manual = node?.widgets?.find((w) => w?.name === "prompt_role")?.value;
        if (manual === "positive" || manual === "negative") return manual;
        return detectRoleFromGraph(node) || "auto";
    }
}

/**
 * Follow the CONDITIONING output downstream to a sampler and read its slot.
 *
 * Cycle-safe and depth-limited: LiteGraph happily holds a loop even though the
 * execution engine would reject it, and an unguarded walk would freeze the tab
 * (the exact failure mode the draft this replaces had).
 */
export function detectRoleFromGraph(startNode) {
    const visited = new Set();
    const queue = [{ node: startNode, depth: 0 }];
    let steps = 0;

    const startsWithSampler = (type) =>
        /^(KSampler|KSamplerAdvanced|SamplerCustom|SamplerCustomAdvanced)/.test(type || "");

    while (queue.length && steps < 256) {
        steps++;
        const { node, depth } = queue.shift();
        if (!node || depth > 12) continue;
        const key = node.id ?? node.type;
        if (visited.has(key)) continue;
        visited.add(key);

        for (const { node: target, slot } of outputTargets(node, 0)) {
            const type = target.type || "";
            if (startsWithSampler(type)) {
                // KSampler: model=0, positive=1, negative=2, latent=3
                if (slot === 2) return "negative";
                if (slot === 1) return "positive";
            }
            if (/_CONDITIONING$|Conditioning/.test(type) || /ConditioningSetArea|ConditioningCombine|ConditioningConcat/.test(type)) {
                queue.push({ node: target, depth: depth + 1 });
            }
        }
    }
    return "";
}
