# [MR draft] CUDA: read `sharedMemPerBlockOptin` via `cudaDeviceGetAttribute` (fixes Blackwell `invalid argument` crash)

> This file is a ready-to-submit pull-request description for **upstream
> `ggml-org/llama.cpp`**. Copy the body below into the PR. It is self-contained.

---

## Title

`CUDA: use cudaDeviceGetAttribute for sharedMemPerBlockOptin to fix sm_120 "invalid argument" crash`

## Summary

On Blackwell (RTX 5090, `sm_120`) with the CUDA 13.x toolkit, `llama-server`
aborts on inference with:

```
CUDA error: invalid argument
  current device: 0, in function ... at ggml/src/ggml-cuda/softmax.cu
GGML_ABORT
```

The crash is **not** in softmax. The real cause is that
`cudaDeviceProp::sharedMemPerBlockOptin` is read incorrectly and yields a garbage
value (~4 GiB), which is later passed to
`cudaFuncSetAttribute(cudaFuncAttributeMaxDynamicSharedMemorySize, …)`; the driver
rejects the bogus size. This PR reads that single value through
`cudaDeviceGetAttribute(cudaDevAttrMaxSharedMemoryPerBlockOptin, …)` instead — a
stable driver API that does not depend on the `cudaDeviceProp` struct layout.

## What breaks

In `ggml_cuda_init()` (`ggml/src/ggml-cuda/ggml-cuda.cu`):

```cpp
info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
```

`info.devices[id].smpbo` is meant to hold the GPU's max opt-in shared memory per
block (≈99 KiB / `101376` on an RTX 5090). On the affected setup it instead holds
`4294967297` (`0x1_0000_0001`).

### Why the read is wrong

`cudaGetDeviceProperties()` fills a `cudaDeviceProp` whose binary layout is fixed
by the **CUDA headers used at build time**. When the **runtime driver's** layout
for that struct differs from those headers, individual fields are read from the
wrong byte offset. We confirmed this on the box:

- A standalone program built with the **same** CUDA 13.2 toolkit reads
  `prop.sharedMemPerBlockOptin == 101376` correctly
  (`offsetof == 672`, `sizeof(cudaDeviceProp) == 1008`).
- Inside the running `llama-server`, the same field reads `4294967297`. Dumping
  the raw struct bytes shows the correct `101376` *is* present at offset 672, but
  the value being picked up is the one at offset **656** (`0x1_0000_0001`).
- `cudaDeviceGetAttribute(cudaDevAttrMaxSharedMemoryPerBlockOptin, …)` returns the
  correct `101376` in every context, because it goes through the driver API rather
  than a versioned struct.

## What it affects

`smpbo` feeds `CUDA_SET_SHARED_MEMORY_LIMIT` (→ `cudaFuncSetAttribute(...,
cudaFuncAttributeMaxDynamicSharedMemorySize, smpbo)`) for every kernel that opts
into large shared memory — softmax, flash-attention (MMA), the MoE id helper, etc.
Requesting ~4 GiB of dynamic shared memory per block is invalid, so the driver
returns `cudaErrorInvalidValue`, `CUDA_CHECK` fires, and the process aborts.

The abort surfaces under whichever op calls the macro first (often `SOFT_MAX`
during prefill), which makes the error message misleading — the softmax math is
fine.

**Impact:** any `sm_120` GPU on a CUDA toolkit/driver combination with this struct
mismatch cannot run inference at all — it aborts on the first kernel that needs
opt-in shared memory.

## The fix

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

The attribute query is the authoritative driver-side source for this value; the
struct read is kept only as a fallback so behaviour is unchanged on platforms
where the attribute query fails. The change is confined to the non-HIP/non-MUSA
`#else` branch; HIP and MUSA paths are untouched.

> `cudaDevAttrMaxSharedMemoryPerBlockOptin` and `cudaDeviceGetAttribute` are
> available since CUDA 9, so this does not raise the minimum toolchain.

## Testing

Environment: RTX 5090 (`sm_120`, cc 12.0), CUDA 13.2.1, driver 595.58.03,
base commit `5f04dc7`.

- **Before:** `llama-server` aborts on the first request
  (`SOFT_MAX failed: CUDA error: invalid argument`) and enters a restart loop.
- **After:** stable. Re-tested the exact crash scenarios — varied prefill lengths
  (3 → 700 tokens), a ~2000-token long-context prompt, and a 6-way concurrent
  burst — with **0 crashes/aborts**, a single process start (no restart loop), and
  coherent output. Standard MMA flash-attention and cooperative softmax run
  normally; no other kernel-path changes were needed.

## Alternatives considered

- **Forcing the VEC flash-attention kernel / skipping cooperative softmax on
  Blackwell** — these were tried first (while the root cause was unknown) and do
  reduce reliance on the `smpbo`-derived `cudaFuncSetAttribute` calls, but they are
  unnecessary once `smpbo` is correct, and they disable faster code paths. The
  attribute-query fix makes them redundant.
- **`-DGGML_CUDA_FORCE_CUBLAS=ON`** — masks the MMQ crash but not the softmax one,
  and only disables the faster MMQ kernels. Not a real fix.

## Out of scope (separate issue)

On the same hardware, `IQ4_NL`-quantized models produce **incoherent output on the
GPU backend** (the `sm_120` dequant kernel appears broken: the same GGUF is
coherent on CPU and `Q4_K_*`/`Q6_K` quants are coherent on GPU). This is unrelated
to the crash fixed here and is worth a separate report.
