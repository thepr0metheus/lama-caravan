# Postmortem: `SOFT_MAX failed: CUDA error: invalid argument` on Blackwell (RTX 5090)

**Date:** 2026-06-15
**Affected host:** the controller — RTX 5090 (Blackwell, `sm_120`, cc 12.0), CUDA 13.2, driver 595.x
**Affected workload:** `lama-cell@8001.service` running `Qwen3.6-35B-A3B-UD-IQ4_NL` (flash attention on, K/V cache `q8_0`)
**Severity:** High — model cell crashed on inference and entered a systemd restart loop; the model was effectively unusable.
**Status:** Resolved. Minimal single-file fix (`ggml-cuda.cu`) codified in [`scripts/install-llama.sh`](../scripts/install-llama.sh) and applied automatically on any `sm_120` host. (Two defensive patches tried during the investigation were verified unnecessary and removed — see §4.)

---

## 1. Symptom

Every inference request (sometimes after the first one, sometimes during warmup/prefill) aborted the server with:

```
CUDA error: invalid argument
  current device: 0, in function ... at .../softmax.cu
  SOFT_MAX failed
```

`GGML_ABORT` then killed the process, systemd restarted it, and the next request crashed again. The same model on other Blackwell hosts showed the same crash intermittently.

The error message pointed at `SOFT_MAX`, which sent us chasing the softmax kernel for a long time. **That was a red herring** — see §3.

---

## 2. The actual root cause

`llama.cpp` reads the GPU's maximum opt-in shared-memory size into `ggml_cuda_device_info::smpbo`:

```cpp
cudaDeviceProp prop;
cudaGetDeviceProperties(&prop, id);
info.devices[id].smpbo = prop.sharedMemPerBlockOptin;   // <-- the bug bites here
```

On this host that field came back as **`4294967297` (`0x1_0000_0001`, ~4 GiB)** instead of the real value **`101376` (99 KiB)**.

### Why the value was garbage: a `cudaDeviceProp` struct-layout mismatch

`cudaGetDeviceProperties` fills a `cudaDeviceProp` struct whose binary layout is defined by the **CUDA toolkit headers used at compile time**. When the **runtime driver's** notion of that struct's layout differs from the headers `llama.cpp` was built against, individual fields are read from the **wrong byte offset**.

We proved this empirically on the box:

- A standalone program compiled with the **same** CUDA 13.2 toolkit read `sharedMemPerBlockOptin` correctly as `101376` (`offsetof` = 672, `sizeof(cudaDeviceProp)` = 1008).
- Inside the running `llama-server`, the field read back `4294967297`. Dumping the raw struct bytes showed the correct `101376` *was* present at offset 672, but the code was effectively picking up the value at offset **656** (`0x1_0000_0001`).
- The `cudaDevAttrMaxSharedMemoryPerBlockOptin` **attribute query** returned the correct `101376` in every context — because that path goes through a stable driver API instead of a versioned struct.

In other words: **`prop.sharedMemPerBlockOptin` is unreliable across this CUDA-toolkit / driver combination; the attribute query is not.**

### How a 4 GiB smpbo turns into "invalid argument"

`llama.cpp` feeds `smpbo` into `cudaFuncSetAttribute(..., cudaFuncAttributeMaxDynamicSharedMemorySize, nbytes)` via the `CUDA_SET_SHARED_MEMORY_LIMIT` macro before launching kernels that opt into large shared memory (softmax, flash-attention MMA, MoE id helper, etc.). Asking the driver to reserve ~4 GiB of dynamic shared memory per block is invalid, so the driver returns `cudaErrorInvalidValue` → `CUDA_CHECK` → `GGML_ABORT`.

The abort surfaced under whichever op happened to call the macro first. For this model that was usually `SOFT_MAX`, hence the misleading message. The fault was **not** in the softmax math at all — it was the shared-memory limit derived from a corrupt `smpbo`.

---

## 3. Investigation path (what we tried, in order)

This is the honest sequence, including the dead ends, so the next person doesn't repeat them.

| # | Hypothesis | Action | Outcome |
|---|-----------|--------|---------|
| 1 | MMQ int8 kernels broken on Blackwell | Built with `GGML_CUDA_FORCE_CUBLAS=ON` | Crash moved from warmup to inference — *masked* one symptom, didn't fix root cause |
| 2 | MMA flash-attn `cudaFuncSetAttribute` fails on Blackwell | Patched `fattn.cu` to force the VEC kernel (aligned-seqlen path) | Crash persisted for arbitrary prompt lengths |
| 3 | VEC patch missed non-aligned seqlens (`K->ne[1] % 256 != 0`) | Added a second VEC fallback in `fattn.cu` outside the `can_use_vector_kernel` block | Crash still reproduced under `SOFT_MAX` |
| 4 | Cooperative softmax launch broken on Blackwell | Patched `softmax.cu` to skip `cudaLaunchCooperativeKernel` on Blackwell | Helped one path, crash still reproduced |
| 5 | **`smpbo` itself is wrong** | Added a debug `fprintf` of `smpbo` in `ggml_cuda_init()` | **Printed `4294967297`** — the smoking gun |
| 6 | Struct-layout mismatch confirmed | Compared standalone-program value, raw struct bytes, and attribute query | Confirmed: struct field bad, attribute query good |
| 7 | **Fix** | Replaced the struct read with `cudaDeviceGetAttribute(cudaDevAttrMaxSharedMemoryPerBlockOptin)` | Crash gone; model stable across many requests |

**Key debugging lesson:** the `GGML_LOG_INFO` lines inside `ggml_cuda_init()` did not appear in our `journalctl` capture (logger callback ordering at init time), so the smpbo value was invisible until we added a raw `fprintf(stderr, ...)`. When a CUDA init value is suspect, print it with `fprintf` to `stderr`, not through the ggml logger.

---

## 4. The fix

### Primary fix (this is the one that actually mattered) — `ggml-cuda.cu`

Replace the unreliable struct field with the stable attribute query. The exact
patch (against `ggml-org/llama.cpp` @ `5f04dc7`):

```diff
diff --git a/ggml/src/ggml-cuda/ggml-cuda.cu b/ggml/src/ggml-cuda/ggml-cuda.cu
@@ -287,8 +287,17 @@ static ggml_cuda_device_info ggml_cuda_init() {
                       id, prop.name, prop.major, prop.minor, device_vmm ? "yes" : "no",
                       (size_t)(prop.totalGlobalMem / (1024 * 1024)));
 #else
-        info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
         info.devices[id].cc = 100*prop.major + 10*prop.minor;
+        // Use cudaDeviceGetAttribute instead of prop.sharedMemPerBlockOptin to avoid
+        // struct layout mismatches between CUDA toolkit versions.
+        {
+            int smpbo_val = 0;
+            if (cudaDeviceGetAttribute(&smpbo_val, cudaDevAttrMaxSharedMemoryPerBlockOptin, id) == cudaSuccess && smpbo_val > 0) {
+                info.devices[id].smpbo = (size_t) smpbo_val;
+            } else {
+                info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
+            }
+        }
         GGML_LOG_INFO("  Device %d: %s, compute capability %d.%d, VMM: %s, VRAM: %zu MiB\n",
                       id, prop.name, prop.major, prop.minor, device_vmm ? "yes" : "no",
                       (size_t)(prop.totalGlobalMem / (1024 * 1024)));
```

With `smpbo = 101376`, every `cudaFuncSetAttribute` call is valid again and the crash disappears.

A full, ready-to-submit upstream merge-request writeup lives in
[`docs/llama-cpp-blackwell-smpbo-MR.md`](llama-cpp-blackwell-smpbo-MR.md).

### Defensive secondary patches — tried during investigation, then REMOVED

During the investigation (steps 2–4 above, before the root cause was known) we
also patched two more files to force Blackwell onto known-good kernel paths:

- **`fattn.cu`** — force the VEC flash-attention kernel on Blackwell.
- **`softmax.cu`** — skip the cooperative `cudaLaunchCooperativeKernel` path.

**These turned out to be unnecessary and were removed.** After reverting both
files to upstream and rebuilding with *only* the `ggml-cuda.cu` smpbo fix, the
server was re-tested on exactly the scenarios that used to crash — varied
prefill lengths (3 → 700 tokens), a ~2000-token long-context prompt, and a
6-way concurrent burst — with **0 crashes/aborts, a single service start (no
restart loop), and coherent output throughout**. With a correct `smpbo`, the
standard MMA flash-attention and cooperative-softmax paths work normally.

The final upstream-ready fix is therefore a **single-file, ~10-line diff** in
`ggml-cuda.cu`.

### Build configuration

`-DGGML_CUDA_FORCE_CUBLAS=ON` was used as a stop-gap during step 1 to dodge the
MMQ crash. Once the smpbo fix is in place the MMQ kernels are safe again, so the
flag was **removed** — it only disables the faster MMQ path and buys nothing.
`install-llama.sh` now builds with default kernel selection.

---

## 4a. Follow-up: garbage generation on `IQ4_NL` (a *separate*, pre-existing bug)

After the crash was fixed, the cell ran but produced **incoherent token soup**
(Chinese characters, random numbers, broken markdown). This looked like the fix
had "broken generation," but it is a **distinct, pre-existing problem** that the
crash had been masking — before the fix the model never got far enough to emit
output at all.

### Bisection

| Test | Result |
|------|--------|
| `Qwen3.6-35B-A3B-UD-IQ4_NL` on GPU (MTP on) | garbage |
| same, MTP off | garbage → **not** MTP |
| same, flash-attention off + f16 cache | garbage → **not** flash attention |
| same, `FORCE_CUBLAS=ON` vs `OFF` | garbage either way → **not** the matmul path / build flag |
| **different model** (`Nex-N2-mini` Q4_K_S) on GPU | **coherent** → build is fine |
| **same model, `Q4_K_M` quant** on GPU | **coherent** → architecture is fine |
| **`IQ4_NL` on CPU** (`-ngl 0`) | **coherent** → the GGUF file is fine |

### Conclusion

`IQ4_NL` is **broken on the Blackwell (`sm_120`) CUDA backend** in this build.
Both the MMQ kernel and the cuBLAS-dequant path garble it, which points at the
`IQ4_NL` dequantization on `sm_120` itself — not at any flag we set, not the
file, not the architecture, not flash attention, not MTP. K-quants
(`Q4_K_M`, `Q5_K_XL`, `Q6_K`) use different kernels and are unaffected.

### Remediation

There is no build flag that fixes `IQ4_NL` on Blackwell (the dequant kernel is
the bug). **Switch the cell to a K-quant.** We moved `lama-cell@8001` from
`IQ4_NL` (18 GiB) to `Q4_K_M` (22 GiB) — verified coherent, fits the 200k-token
q8_0 KV cache in 32 GiB VRAM (~27 GiB used). `Q4_K_S` (20 GiB) is the closest
size match if more KV headroom is needed.

> **Rule of thumb for Blackwell:** avoid `IQ*`/`IQ4_NL` quants for now; prefer
> `Q4_K_M`/`Q5_K_*`/`Q6_K`. (Worth filing/tracking upstream as an `IQ4_NL`
> `sm_120` dequant bug.)

---

## 5. How the fix is delivered

The single `ggml-cuda.cu` smpbo patch is applied **automatically** by [`scripts/install-llama.sh`](../scripts/install-llama.sh) whenever an `sm_120` GPU is detected (`apply_blackwell_patches`). The patch function is **idempotent** — it detects already-patched source and skips, and no-ops gracefully if upstream changes the surrounding code (printing `[skip] ... pattern not found`).

To deploy on any Blackwell host:

```sh
cd /path/to/lama-caravan
bash scripts/install-llama.sh --force      # rebuilds llama.cpp with the patches, restarts cells
```

---

## 6. Scope: do the client hosts or `llm-easy-route-agent` need a code change?

**No.** The bug lives entirely in the **`llama-server` CUDA backend** (`ggml-cuda`). Neither component runs CUDA code:

- **`llm-easy-route-agent`** (per-client host) only starts/stops/proxies `llama-server` processes and reports status. It spawns the binary; it does not touch the GPU.
- The orchestration/config layer over the agents runs on a client host.

The "rare crashes with the same model" seen elsewhere were **the same llama.cpp CUDA bug**, observed through different cells/hosts. The remediation is therefore **operational, not a code change in those services**:

> **Every Blackwell (`sm_120`) host that runs this model must rebuild `llama.cpp` with `install-llama.sh`.** Hosts with older GPUs (Ampere/Ada) are unaffected — `prop.sharedMemPerBlockOptin` is correct there, and the patches are gated behind the `sm_120` check.

Action item: run `install-llama.sh --force` on each Blackwell client host (and any orchestration host if it also serves a Blackwell-backed cell).

---

## 7. Lessons learned

1. **`cudaDeviceProp` is a versioned ABI.** When toolkit and driver disagree, struct fields silently read from the wrong offset. Prefer `cudaDeviceGetAttribute` for individual values that feed into driver calls.
2. **The op named in a CUDA abort is often just "who called the failing helper first," not the culprit.** `SOFT_MAX failed` was three layers removed from the real cause.
3. **Print suspicious init-time values with raw `fprintf(stderr)`,** not the framework logger — the logger callback may not be wired up yet during `ggml_cuda_init()`.
4. **Masking fixes (`FORCE_CUBLAS`, forcing VEC) move the symptom; they don't prove the cause.** The breakthrough came only from printing the actual value.

---

## 8. References (source locations in `llama.cpp`)

- `ggml/src/ggml-cuda/ggml-cuda.cu` — `ggml_cuda_init()`, `smpbo` assignment, `CUDA_SET_SHARED_MEMORY_LIMIT` macro definition (`common.cuh`)
- `ggml/src/ggml-cuda/softmax.cu` — `soft_max_f32_cuda`, cooperative launch path
- `ggml/src/ggml-cuda/fattn.cu` — flash-attention kernel selection (`can_use_vector_kernel`)
- `ggml/src/ggml-cuda/common.cuh` — `GGML_CUDA_CC_BLACKWELL = 1200`, `CUDA_CHECK`, `CUDA_SET_SHARED_MEMORY_LIMIT`
