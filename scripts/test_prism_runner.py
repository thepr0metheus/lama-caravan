#!/usr/bin/env python3
"""Native Prism cells keep GGUF config and cannot fall back to stock llama."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from caravan.admin import fleet_clients as fc
from caravan.admin.config_builder import build_local_llama_command, build_remote_llama_args
from caravan.admin.hf import _extract_quant
from caravan.admin.launch import render_launch_script
from caravan.admin.model_locator import Locations
from caravan.common.errors import AppError
from caravan.domain.runner import for_config, registry_json


class PrismRunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="prism-runner-"))
        self.config = {"RUNNER": "prism", "MODEL_FILE": "Bonsai-PQ2_0.gguf", "MMPROJ_FILE": "mmproj-BF16.gguf",
                       "LLAMA_MODELS_DIR": str(self.root), "PORT": "22013", "CTX_SIZE": "8192",
                       "N_GPU_LAYERS": "0", "PARALLEL": "1", "CACHE_TYPE_K": "q8_0", "CACHE_TYPE_V": "q8_0"}
        for name in (self.config["MODEL_FILE"], self.config["MMPROJ_FILE"]): (self.root / name).write_bytes(b"GGUF")

    def test_registry_declares_shared_native_capabilities(self):
        row = next(row for row in registry_json() if row["id"] == "prism")
        self.assertTrue(row["llamaConfig"])
        self.assertTrue(row["tokenContext"])
        self.assertFalse(row["commandPath"])
        self.assertEqual(row["modelField"], "MODEL_FILE")
        self.assertEqual(row["api"], "openai")

    def test_binary_and_args_are_separate_from_stock(self):
        prism = build_local_llama_command(self.config, llama_home="/stock", locations=Locations())
        stock_config = {**self.config, "RUNNER": "llama-server"}
        stock = build_local_llama_command(stock_config, llama_home="/stock", locations=Locations())
        self.assertNotEqual(prism[0], stock[0])
        self.assertIn("prismml/current/llama-server", prism[0])
        self.assertEqual(prism[1:], stock[1:])
        self.assertIn("--mmproj", prism)
        self.assertIn("--cache-type-k", prism)

    def test_preview_preserves_runtime_and_cpu_isolation(self):
        script = render_launch_script(self.config, locations=Locations())
        self.assertIn('RUNNER="prism"', script)
        self.assertIn("prismml/current/llama-server", script)
        self.assertIn('CUDA_VISIBLE_DEVICES=""', script)
        self.assertIn("LD_LIBRARY_PATH=", script)

    def test_stock_refuses_known_prism_quants(self):
        for quant in ("PQ2_0", "PTQ1_0"):
            with self.subTest(quant=quant), self.assertRaisesRegex(AppError, "PrismML"):
                for_config({}).preflight_start({}, f"Bonsai-{quant}.gguf")
        for_config(self.config).preflight_start(self.config)
        for_config({}).preflight_start({}, "Qwen-Q4_K_M.gguf")

    def test_scout_payload_and_capability_gate(self):
        body = {"hostId": "box", "port": 22013, "modelPath": self.config["MODEL_FILE"], "config": self.config}
        with patch.object(fc, "current_locations", return_value=Locations()), \
             patch.object(fc, "topology_store", return_value={"hosts": {"box": {}}}):
            with self.assertRaisesRegex(AppError, "update caravan-scout"): fc.scout_start_payload(body)
        with patch.object(fc, "current_locations", return_value=Locations()), \
             patch.object(fc, "topology_store", return_value={"hosts": {"box": {"prismRuntime": {"supported": True}}}}):
            payload = fc.scout_start_payload(body)
        self.assertNotIn("cellKind", payload)
        self.assertNotIn("shellLine", payload)
        self.assertEqual(payload["config"]["RUNNER"], "prism")
        self.assertEqual(payload["args"], build_remote_llama_args(self.config))
        self.assertIn("{{MMPROJ_PATH}}", payload["args"])
        self.assertEqual(payload["env"]["CUDA_VISIBLE_DEVICES"], "")

    def test_hf_quant_labels(self):
        for quant in ("PQ2_0", "PTQ1_0"):
            self.assertEqual(_extract_quant(f"Ternary-Bonsai-2-27B-{quant}.gguf"), quant)


if __name__ == "__main__": unittest.main()
