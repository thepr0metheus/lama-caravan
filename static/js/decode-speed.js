/**
 * How fast a model can answer, at best, from where its weights lie (the owner, 2026-11-03: «can we show some rough counter when we lay the
 * weights out»). A token reads every weight once: those on the card from the card's memory; those left in RAM (vLLM's CPU_OFFLOAD_GB) come
 * over the card's bus first. So a token takes a card's share ÷ its memory's bandwidth + what stays in RAM ÷ its bus's, on the slowest card a
 * start takes.
 *
 * A bound by the bandwidths, drawn as "≈", not a measurement. Checked against the owner's measurements on the RTX 3090 (PCIe 4.0 x8) of the
 * GPU machine, 2026-11-02, Cosmos-Reason2-2B BF16 (4.54 GiB) in vLLM: all on the card this rule says 192 tokens/s and vLLM did 182–184; with
 * 3 GiB left in RAM it says 4.8 and vLLM did 5.2–5.3. A model of experts reads only part of its weights for a token, which part this rule does
 * not know: it says nothing for one, nor for a card or a bus it does not know.
 */
export class DecodeSpeed {
  /** GB/s of a card's memory, the maker's figure, by the model its name says. A model sold with two memories of two speeds (the RTX 3060,
   *  the RTX 3080) is not here: its name does not say which it is. */
  static MEMORY_GBPS = {
    "RTX 3060 Ti": 448, "RTX 3070": 448, "RTX 3070 Ti": 608, "RTX 3080 Ti": 912, "RTX 3090": 936, "RTX 3090 Ti": 1008,
    "RTX 4060": 272, "RTX 4060 Ti": 288, "RTX 4070": 504, "RTX 4070 SUPER": 504, "RTX 4070 Ti": 504, "RTX 4070 Ti SUPER": 672,
    "RTX 4080": 717, "RTX 4080 SUPER": 736, "RTX 4090": 1008,
    "RTX 5060 Ti": 448, "RTX 5070": 672, "RTX 5070 Ti": 896, "RTX 5080": 960, "RTX 5090": 1792,
  };

  /** GB/s one PCIe lane carries, by generation, after its line code. */
  static LANE_GBPS = { 1: 0.25, 2: 0.5, 3: 0.985, 4: 1.969, 5: 3.938 };

  /** The card's model as the table names it: "NVIDIA GeForce RTX 4070 Ti SUPER" is "RTX 4070 Ti SUPER"; "" for a name that names none. */
  static modelOf(name) {
    const found = /RTX\s+(\d{4})(\s+Ti)?(\s+SUPER)?\b/i.exec(String(name || ""));
    return found ? `RTX ${found[1]}${found[2] ? " Ti" : ""}${found[3] ? " SUPER" : ""}` : "";
  }

  /** GB/s of the card's memory, or null for a card the table does not know. */
  static memoryOf(card) {
    return DecodeSpeed.MEMORY_GBPS[DecodeSpeed.modelOf(card?.name)] || null;
  }

  /** GB/s the card's bus carries, or null when its machine did not say its link (a scout before 2.45.0, a driver that knows no such field). */
  static busOf(card) {
    const lane = DecodeSpeed.LANE_GBPS[Number(card?.pcieGen)];
    const width = Number(card?.pcieWidth);
    return lane && width > 0 ? lane * width : null;
  }

  /** `{ full, now, slower }`: tokens/s with every weight on the cards, tokens/s as laid out, and how many times slower that is; null when a
   *  figure is not known. `weightsGiB` is cut evenly over `cards`; `ridesGiB` of each card's cut stays in RAM; `experts` is the model's (0: it
   *  has none; null: not known). */
  static of({ cards = [], weightsGiB = 0, ridesGiB = 0, experts = null } = {}) {
    if (!(weightsGiB > 0) || !cards.length || experts !== 0) return null;
    const share = (weightsGiB * 2 ** 30) / cards.length;
    const rides = Math.min(Math.max(0, Number(ridesGiB) || 0) * 2 ** 30, share);
    let full = 0;
    let now = 0;
    for (const card of cards) {
      const memory = DecodeSpeed.memoryOf(card);
      // A card all of whose weights are on it reads nothing over its bus: its bus need not be known.
      const bus = rides > 0 ? DecodeSpeed.busOf(card) : Infinity;
      if (!memory || !bus) return null;
      full = Math.max(full, share / (memory * 1e9));
      now = Math.max(now, share / (memory * 1e9) + rides / (bus * 1e9));
    }
    return { full: 1 / full, now: 1 / now, slower: now / full };
  }

  /** A speed in words: a decimal under 10 tokens/s, whole ones from there (9.96 is "10", not "10.0"). */
  static said(perSecond) {
    const tenths = Math.round(perSecond * 10) / 10;
    return tenths < 10 ? tenths.toFixed(1) : String(Math.round(perSecond));
  }
}
