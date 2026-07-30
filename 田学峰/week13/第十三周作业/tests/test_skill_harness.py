import unittest
from pathlib import Path

from skill_harness.loader import ProgressiveLoader
from skill_harness.matcher import SkillMatcher
from skill_harness.registry import SkillRegistry


ROOT = Path(__file__).resolve().parents[1]


class SkillHarnessTests(unittest.TestCase):
    def test_discover_metadata_only(self):
        skills = SkillRegistry(ROOT / "skills").discover()
        names = {skill.name for skill in skills}
        self.assertIn("flash-card", names)
        self.assertIn("baoyu-diagram", names)
        self.assertTrue(all(skill.frontmatter_chars > 0 for skill in skills))

    def test_match_flash_card(self):
        skills = SkillRegistry(ROOT / "skills").discover()
        matches = SkillMatcher().rank("给我做 crazy 的 flash card", skills)
        self.assertTrue(matches)
        self.assertEqual(matches[0].skill.name, "flash-card")

    def test_load_diagram_reference_progressively(self):
        registry = SkillRegistry(ROOT / "skills")
        metadata = registry.get("baoyu-diagram")
        context = ProgressiveLoader().build_context("画一个系统架构图", metadata)
        self.assertTrue(context.skill.content)
        self.assertTrue(context.references)
        self.assertTrue(any(ref.path.name == "architecture.md" for ref in context.references))


if __name__ == "__main__":
    unittest.main()
