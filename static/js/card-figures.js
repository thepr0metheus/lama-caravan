// What a device's figures read as: the row of a card on a machine's rack (machine-head.js) when it is drawn, and the monitor's tick
// (charts.js) that keeps it current. One rule for both, or a row would change its look with its first tick. A figure nobody reported
// reads as a dash, never as a zero.
export class CardFigures {
  static load(pct) {
    return pct === null || pct === undefined ? "—" : `${Math.round(pct)}%`;
  }

  /** Used of total, in GB, each as the machine said it. */
  static memory(usedGb, totalGb) {
    return `${usedGb === null || usedGb === undefined ? "—" : Number(usedGb).toFixed(1)} / ${totalGb === null || totalGb === undefined ? "—" : Number(totalGb).toFixed(1)}`;
  }

  static power(watts) {
    return watts === null || watts === undefined ? "—" : `${Number(watts).toFixed(1)} W`;
  }
}
