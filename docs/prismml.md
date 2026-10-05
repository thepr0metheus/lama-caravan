# PrismML / Bonsai cells

Choose **PrismML** in the cell editor to serve Bonsai GGUF models using Prism's
`PQ2_0` and `PTQ1_0` tensor formats. These files need the PrismML fork of
llama.cpp; an ordinary llama.cpp binary does not understand their tensor types.
The shared GGUF form keeps model/projector selection, CPU/GPU placement, context,
KV cache, presets, autostart, logs, health, slots and OpenAI-compatible routing.

Update caravan-scout before using this runner. The controller checks the scout's
`prismRuntime.supported` capability and refuses an old scout instead of silently
starting the stock binary. Selecting a file named PQ2_0/PTQ1_0 selects PrismML in
the editor; a stock runner refuses these filenames with a specific explanation.
Renamed GGUF files may need manual runner selection.

On first start the scout installs the pinned official release
`prism-b10743-adfffbe` under `~/.local/share/caravan/prismml/`. It checks the
release asset's SHA-256, extracts into a temporary directory, verifies the
binary and publishes the installation only after success. Download progress
appears on the cell. Subsequent starts reuse the runtime. The process and its
saved start.sh name the versioned binary and its own library directories;
ordinary llama.cpp cells keep their configured `llamaServerBin`.

Managed platforms: Linux x86_64 CPU/CUDA, Linux arm64 CPU, macOS arm64/x86_64.
CUDA selection uses the driver's supported CUDA version: >=13.3 chooses 13.3,
>=12.8 chooses 12.8, >=12.4 chooses 12.4. A CPU-only cell hides CUDA devices.
Linux x86_64 Vulkan/ROCm require explicit scout configuration and matching host
drivers. Windows is not currently a managed Prism runtime in the scout.

The scout's optional config.json fields are `prismRuntimeDir`, `prismBackend`
(`auto`, `cpu`, `cuda`, `vulkan`, `rocm`) and `prismServerBin` (an already installed
Prism server with matching libraries beside it). The default installs on demand;
no separate server service is needed. To install ahead of time on a scout host:

```sh
python3 -m caravan_scout.prism install
python3 -m caravan_scout.prism
```

A Prism release can lag upstream flags. The scout checks the generated options
against the selected binary's --help and names unsupported options before
loading the model. It never silently drops a requested flag.

Runtime compatibility does not guarantee that a memory plan fits. Bonsai 27B
PQ2_0 weights alone occupy about 6.7 GiB; projector, KV cache and work buffers
add to this. Start with a modest context (e.g. 8192), one slot and appropriate
GPU layers, especially when other cells already occupy the card. Use CPU
placement or partial offload when GPU memory is insufficient.

Official sources: [PrismML llama.cpp](https://github.com/PrismML-Eng/llama.cpp),
[Bonsai demo](https://github.com/PrismML-Eng/Bonsai-demo),
[pinned release](https://github.com/PrismML-Eng/llama.cpp/releases/tag/prism-b10743-adfffbe).
