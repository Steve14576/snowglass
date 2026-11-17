"""无需读取权重的配置与张量归属回归：uv run --no-project python -m unittest discover -s tests。"""
import copy
import unittest
from scripts import build_topology_qwen35 as t


class TopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, _ = t.load_config(t.CONFIG)
        cls.cfg = t.parse_config(cls.doc)
        cls.text, _ = t.load_inv(t.INV_TEXT)
        cls.vision, _ = t.load_inv(t.INV_VIS)

    def test_actual_inventory_coverage(self):
        text, vision = t.Builder(self.text, "text", self.cfg), t.Builder(self.vision, "vision", self.cfg)
        layers = t.build_text(text)
        t.build_vision(vision)
        self.assertEqual((len(text.blocks), len(vision.blocks)), (259, 110))
        self.assertEqual((text.coverage(), vision.coverage()), ([], []))
        self.assertEqual(sum(b["params"] for b in text.blocks), sum(x["n_elements"] for x in self.text.values()))
        self.assertEqual(sum(b["params"] for b in vision.blocks), sum(x["n_elements"] for x in self.vision.values()))
        self.assertEqual(sum(x["kind"] == "full" for x in layers), 8)
        self.assertEqual(len(text.used), 427)
        self.assertEqual(len(vision.used), 334)

    def test_config_only_and_layer_count(self):
        doc = copy.deepcopy(self.doc)
        doc["text_config"]["num_hidden_layers"] = 6
        doc["text_config"]["layer_types"] = ["full_attention"] + ["linear_attention"] * 5
        cfg = t.parse_config(doc)
        builder = t.Builder(None, "text", cfg)
        layers = t.build_text(builder)
        self.assertEqual(len(builder.blocks), 6 * 8 + 3)
        self.assertEqual(layers[0]["kind"], "full")
        self.assertEqual(layers[3]["kind"], "gdn")
        self.assertTrue(all(x["binding"] == "config_unbound" for b in builder.blocks for x in b["tensors"]))

    def test_layer_types_length_rejected(self):
        doc = copy.deepcopy(self.doc)
        doc["text_config"]["layer_types"].pop()
        with self.assertRaises(ValueError):
            t.parse_config(doc)

    def test_unsupported_architecture_rejected(self):
        doc = copy.deepcopy(self.doc)
        doc["text_config"]["model_type"] = "unverified"
        with self.assertRaises(ValueError):
            t.parse_config(doc)

    def test_bad_numeric_type_rejected(self):
        doc = copy.deepcopy(self.doc)
        doc["text_config"]["num_hidden_layers"] = "32"
        with self.assertRaises(ValueError):
            t.parse_config(doc)

    def test_shape_conflict_rejected(self):
        cfg = dict(self.cfg, hidden=2048)
        builder = t.Builder(self.text, "text", cfg)
        with self.assertRaises(ValueError):
            builder.ref("blk.0.attn_norm.weight")

    def test_vision_shape_conflict_rejected(self):
        doc = copy.deepcopy(self.doc)
        doc["vision_config"]["hidden_size"] = 2048
        builder = t.Builder(self.vision, "vision", t.parse_config(doc))
        with self.assertRaises(ValueError):
            builder.ref("v.blk.0.ln1.weight")

    def test_gate_flag_drives_q_shape(self):
        doc = copy.deepcopy(self.doc)
        doc["text_config"]["attn_output_gate"] = False
        cfg = t.parse_config(doc)
        self.assertEqual(t.expected_text_shape("blk.3.attn_q.weight", cfg), [4096, 4096])

    def test_duplicate_reference_rejected(self):
        builder = t.Builder(self.text, "text", self.cfg)
        builder.ref("blk.0.attn_norm.weight", block_id="a")
        with self.assertRaises(ValueError):
            builder.ref("blk.0.attn_norm.weight", block_id="b")

    def test_gdn_group_has_independent_tensors(self):
        builder = t.Builder(self.text, "text", self.cfg)
        t.build_text(builder)
        group = next(b for b in builder.blocks if b["id"] == "L00.mix1")
        self.assertEqual(len(group["tensors"]), 7)
        self.assertTrue(all(x["rows"] is None for x in group["tensors"]))
        self.assertEqual(group["fold"]["basis"], "per_tensor")


if __name__ == "__main__":
    unittest.main()
