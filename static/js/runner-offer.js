// Whether a runner of the registry is offered for a model of the list at all.
// One with no tab in the cell editor (an engine of its own, as Ollama) and one
// that takes nothing from the model list (sharedPicker "ignored": a voice engine
// that fetches its own weights, a command) runs no model of it — offered, a
// voice clone stood among the runners of a 70B chat model (2026-10-26). The
// new-cell wizard's runner step (add-model.js) and the launch builder of a
// machine's page (machine-build.js) offer by this one rule. A module of its own
// and a light one: the machine page's modules read no cell editor.
export class RunnerOffer {
  static offered(row) {
    return !!row && row.editorTab !== false && row.sharedPicker !== "ignored";
  }
}
