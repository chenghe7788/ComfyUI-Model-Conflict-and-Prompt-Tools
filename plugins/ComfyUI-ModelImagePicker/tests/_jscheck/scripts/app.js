/**
 * Stub of ComfyUI's ../../scripts/app.js for the headless conflict-module test.
 * It only has to provide the pieces model_conflict.js touches: `app.graph._nodes`.
 */
export const app = {
    graph: globalThis.__FAKE_GRAPH || { _nodes: [] },
};
