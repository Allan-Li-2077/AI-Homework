from pathlib import Path
import tempfile
import unittest

from skill_harness import ProgressiveSkillHarness

ROOT = Path(__file__).parents[1]


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, instructions, input_text):
        self.calls += 1
        if self.calls == 1:
            return '{"action":"load_resources","paths":["references/style.md"]}'
        self.last_input = input_text
        return '{"action":"finish","result":{"message":"小明，欢迎你来到这里 ☀"}}'


class HarnessTests(unittest.TestCase):
    def harness(self, llm_client=None):
        return ProgressiveSkillHarness(ROOT / "skills", llm_client=llm_client)

    def test_discovers_metadata(self):
        self.assertEqual(
            {item.name for item in self.harness().list_skills()},
            {"calculator", "greeter"},
        )

    def test_routes_and_executes_calculator_without_resources(self):
        result = self.harness().run("帮我计算 (12 + 8) / 4")
        self.assertEqual(result.skill, "calculator")
        self.assertEqual(result.output["value"], 5)
        self.assertNotIn("load_resource", [event.stage for event in result.events])

    def test_resource_is_loaded_only_after_skill_requests_it(self):
        fake = FakeLLM()
        result = self.harness(fake).run("给小明写一句欢迎语")
        stages = [event.stage for event in result.events]
        self.assertEqual(result.skill, "greeter")
        self.assertIn("小明", result.output["message"])
        self.assertLess(stages.index("llm_call"), stages.index("load_resource"))
        self.assertEqual(stages.count("llm_call"), 2)
        self.assertIn("语气：友好", fake.last_input)

    def test_llm_cannot_load_resource_outside_index(self):
        class UnsafeLLM:
            def complete(self, instructions, input_text):
                return '{"action":"load_resources","paths":["../secret.txt"]}'

        with self.assertRaisesRegex(ValueError, "资源索引外"):
            self.harness(UnsafeLLM()).run("写欢迎语", "greeter")

    def test_unknown_request_does_not_load_skill_instructions(self):
        with self.assertRaises(LookupError):
            self.harness().run("完全不相关的请求 xyz")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            skills = Path(directory) / "skills"
            root = skills / "unsafe"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text(
                "---\nname: unsafe\ndescription: unsafe\nkeywords: [\"unsafe\"]\n"
                "entrypoint: ../outside.py\n---\n# unsafe\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "路径越界"):
                ProgressiveSkillHarness(skills).run("unsafe", "unsafe")


if __name__ == "__main__":
    unittest.main()
