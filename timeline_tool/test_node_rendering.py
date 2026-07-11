"""节点菱形尺寸与抗锯齿渲染测试。"""
import unittest

import config
from timeline_track import render_antialiased_diamond


class TestNodeRendering(unittest.TestCase):
    def test_node_diamond_is_slightly_smaller(self):
        self.assertEqual(config.NODE_DIAMOND_SIZE["h"], 6)
        self.assertEqual(config.NODE_DIAMOND_SIZE["w"], 3.5)

    def test_antialiased_diamond_contains_partial_alpha_edges(self):
        image = render_antialiased_diamond(
            fill="#ff6347",
            outline="#ffffff",
            outline_width=1,
            half_width=4,
            half_height=7,
        )
        alpha_values = set(image.getchannel("A").get_flattened_data())
        self.assertIn(0, alpha_values)
        self.assertIn(255, alpha_values)
        self.assertTrue(any(0 < value < 255 for value in alpha_values))


if __name__ == "__main__":
    unittest.main()
