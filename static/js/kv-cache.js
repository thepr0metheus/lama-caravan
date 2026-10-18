// Which pair of flash attention and V cache type llama.cpp starts with: the browser's copy of
// caravan/common/kv_cache.py, so Apply says so before the cell crashes four times and gives up.
//
// llama.cpp keeps the V half of the KV cache in a quantized type (q8_0, q4_0 …) only with flash
// attention on; with it off the server exits at once with "quantized V cache requires flash_attn to
// be enabled". The form of a new cell offered exactly that pair (2026-10-14). The two copies of the
// rule are held together by one table of cases (scripts/fixtures/kv-cache-cases.json) that both
// snapshots run (scripts/test_kv_cache.py, scripts/test_js_kv_cache.py).
export class KvCache {
  //: The cache types that hold plain numbers, so need no flash attention. "" is the field left
  //: empty: llama.cpp's own default, f16.
  static PLAIN = ["", "f32", "f16", "bf16"];

  // The quantized V cache type this config pairs with flash attention OFF, or "" when the pair is
  // fine. Off means stated and not a yes: an empty field is not a choice, llama.cpp then decides.
  static refusedType(config) {
    const cfg = config || {};
    const flash = String(cfg.ENABLE_FLASH_ATTN ?? "").trim().toLowerCase();
    if (!flash || ["1", "true", "yes", "on"].includes(flash)) return "";
    const kind = String(cfg.CACHE_TYPE_V ?? "").trim().toLowerCase();
    return KvCache.PLAIN.includes(kind) ? "" : kind;
  }
}
