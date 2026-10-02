/**
 * SmartCLIP frontend extension
 * ============================
 * Adds a "选择提示词" button, keeps the detected architecture in sync (live wire
 * trace + the node's own runtime report) and opens the word-list dialog with the
 * right role pre-selected.
 *
 * The button is attached to the *stock* CLIPTextEncode as well as to
 * SmartCLIPTextEncode.  The dialog only needs a `text` widget plus the CLIP wire
 * to trace, so nobody has to swap existing nodes just to reach the word lists -
 * that was the whole point of the "extend the native node's UI" alternative in
 * the design review.  On the stock node there is no runtime payload, so the
 * architecture comes from the wire trace (server-side /smart_clip/detect) and is
 * marked as a prediction in the dialog.
 */

import { app } from "../../scripts/app.js";
import { ModelTracker, detectRoleFromGraph } from "./model_tracker.js";
import { PromptDialog } from "./prompt_dialog.js";

const SMART_NODE = "SmartCLIPTextEncode";
/** Node types that get the prompt-dialog button (any node with a `text` widget). */
const DIALOG_NODE_TYPES = [SMART_NODE, "CLIPTextEncode", "CLIPTextEncodeSDXL"];
const EXT_NAME = "SmartCLIP";

/** Does this node have the multiline prompt widget the dialog writes into? */
function findTextWidget(node) {
    return (node?.widgets || []).find((w) => w?.name === "text") || null;
}

app.registerExtension({
    name: `${EXT_NAME}.Extension`,

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!DIALOG_NODE_TYPES.includes(nodeData?.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            try {
                // Only where the dialog can actually do something.
                if (!findTextWidget(this)) {
                    console.warn(`[${EXT_NAME}] ${nodeData.name}: no "text" widget, button skipped`);
                    return result;
                }
                const button = this.addWidget("button", "📝 选择提示词", null, () => {
                    const model = ModelTracker.getModel(this);
                    const role = ModelTracker.detectRole(this);
                    PromptDialog.open(this, model, role);
                    // Re-trace while the dialog is already up.  Switching the
                    // checkpoint is a *widget* change, which fires no connection
                    // callback, so without this the dialog and its embedding
                    // badges would keep the previous model's verdict until the
                    // page was reloaded.
                    ModelTracker.refreshFromGraph(this).then(() => {
                        const dialog = PromptDialog._current;
                        if (dialog && dialog.node === this) {
                            dialog.setModel(ModelTracker.getModel(this));
                        }
                    });
                });
                // never serialise the button or its label into the workflow
                button.serialize = false;
                button.options = Object.assign({}, button.options, { serialize: false });

                ModelTracker.init(this);
                ModelTracker.refreshFromGraph(this);
            } catch (err) {
                console.error(`[${EXT_NAME}] node setup failed:`, err);
            }

            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            // a workflow was just loaded: re-derive what we can from the graph
            try {
                ModelTracker.init(this);
                ModelTracker.refreshFromGraph(this);
            } catch (err) {
                console.warn(`[${EXT_NAME}] restore failed:`, err);
            }
            return result;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected, linkInfo) {
            const result = onConnectionsChange?.apply(this, arguments);
            try {
                // type 1 = input, 2 = output (LiteGraph convention)
                if (type === 1 || type === 2) {
                    ModelTracker.refreshFromGraph(this);
                }
            } catch (err) {
                console.warn(`[${EXT_NAME}] connection refresh failed:`, err);
            }
            return result;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            const result = onRemoved?.apply(this, arguments);
            try {
                PromptDialog._current?.close?.();
            } catch (err) {
                /* ignore */
            }
            return result;
        };
    },

    /**
     * Node executed: `output.smart_clip` is the ui payload the backend sent.
     * Its values arrive as arrays because execution.py flattens ui dicts.
     * (Only SmartCLIPTextEncode sends one; the stock node just uses the trace.)
     */
    nodeCreated(node) {
        const type = node?.comfyClass || node?.type;
        if (!DIALOG_NODE_TYPES.includes(type)) return;
        try {
            ModelTracker.init(node);
            ModelTracker.refreshFromGraph(node);
        } catch (err) {
            console.warn(`[${EXT_NAME}] late init failed:`, err);
        }
    },
});

/** Handy for the browser console: SmartCLIPDebug.role(node) / .model(node) */
globalThis.SmartCLIPDebug = {
    role: (node) => detectRoleFromGraph(node) || "auto",
    model: (node) => ModelTracker.getModel(node),
    state: (node) => ModelTracker.state(node),
};

console.log(`[${EXT_NAME}] loaded (CLIP text encode with architecture-aware presets)`);
