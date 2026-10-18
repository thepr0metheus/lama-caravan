"""One table of file names and the quant read off each, for the two places that read it.

caravan/admin/hf.py (`_extract_quant`) labels every file of /api/hf/files, and that label names the folder a download lands in
(<model>/<author>/<quant>/). static/js/hf-repo-view.js (`HfQuant.fromName`) reads the quant off the name of a companion file
(the server gives mmproj and MTP files none). The two patterns are copies of each other, so both are run against THIS table:
scripts/test_hf_list_files.py and scripts/test_js_hf_repo_view.py. A name added here is read the same way on both sides, or
the one that differs turns red.
"""

#: (file name, the quant read off it; "" when the name carries none)
QUANT_CASES = [
    # a whole file
    ("Model-Q4_K_M.gguf", "Q4_K_M"),
    ("m-Q8_0.gguf", "Q8_0"),
    ("m-UD-Q4_K_XL.gguf", "Q4_K_XL"),
    ("m-IQ4_XS.gguf", "IQ4_XS"),
    ("m-BF16.gguf", "BF16"),
    ("m-f16.gguf", "F16"),
    ("x-nvfp4.gguf", "NVFP4"),
    ("m-MXFP4.gguf", "MXFP4"),
    ("m-PQ2_0.gguf", "PQ2_0"),
    ("m-PTQ1_0.gguf", "PTQ1_0"),
    ("mmproj-BF16.gguf", "BF16"),
    ("mtp-gemma-4-12B-it-Q8_0.gguf", "Q8_0"),
    ("mtp-q2_0.gguf", "Q2_0"),
    # no quant in the name
    ("m-imatrix.gguf", ""),
    ("mtp-gemma-4-31B-it.gguf", ""),
    # the parts of a split model: "-00003-of-00006" is no part of the quant. Until 1.3.565 every Q… quant read it in
    # ("Q8_0-00003-OF-00006"): each part was a row of its own on /hf and a folder of its own on disk.
    ("Qwen3.8-Flash-Next-Q8_0-00001-of-00006.gguf", "Q8_0"),
    ("Qwen3.8-Flash-Next-Q8_0-00003-of-00006.gguf", "Q8_0"),
    ("Model-Q4_K_M-00001-of-00002.gguf", "Q4_K_M"),
    ("Model-Q4_K_M-00002-of-00002.gguf", "Q4_K_M"),
    ("Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00003.gguf", "Q4_K_XL"),
    ("Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf", "IQ4_XS"),
    ("Qwen3.8-Flash-Next-BF16-00001-of-00008.gguf", "BF16"),
    ("m-Q6_K-00002-of-00005.gguf", "Q6_K"),
    ("m-Q2_K_XL-00001-of-00002.gguf", "Q2_K_XL"),
    ("m-Q5_K_S-00001-of-00002.GGUF", "Q5_K_S"),
    # the names of the repositories the report came from, as they are listed there (read 2026-10-17: ISTA-DASLab's GSQ-RCO pack and its
    # Coder, ukisai's Swift 1.5, Unsloth's UD packs). The Q2_0 and UD-Q4_K_XL parts were the rows that read as "Q2_0-00001-OF-00002".
    ("Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf", "Q2_0"),
    ("Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00002-of-00002.gguf", "Q2_0"),
    ("Swift-Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf", "Q2_0"),
    ("Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf", "Q4_K_XL"),
    ("Qwen3.8-Flash-Next-UD-Q4_K_XL-00004-of-00004.gguf", "Q4_K_XL"),
    # the IQ packs never swallowed their tail (their pattern stops at the underscore group); they must read as they did
    ("Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf", "IQ3_S"),
    ("Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf", "IQ2_XS"),
    ("Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf", "IQ1_M"),
    # the whole files next to them in the same repositories
    ("mtp-Qwen3.8-Flash-Next-Q4_K_M.gguf", "Q4_K_M"),
    ("mmproj-Qwen3.8-Flash-Next-BF16.gguf", "BF16"),
    ("imatrix-swiftfn-v1mix.gguf", ""),
    # the tail alone is no quant either
    ("m-00001-of-00002.gguf", ""),
]
