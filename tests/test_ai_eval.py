import json
import os
import unittest
from pathlib import Path

from AIModel.agent import AIResponder
from AIModel.agent import get_ai_responder


class _FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, messages, max_tokens=None) -> str:
        return self._content


class TestAIActionParsing(unittest.TestCase):
    def test_valid_action_parsing(self) -> None:
        ai = AIResponder()
        ai.enabled = True
        ai._client = _FakeClient('{"reply":"ok","action":"send_code","args":{}}')
        response = ai.respond("test", {"active_rental_count": 1})
        self.assertIsNotNone(response)
        self.assertEqual(response.action, "send_code")
        self.assertEqual(response.reply, "ok")

    def test_invalid_action_defaults_to_none(self) -> None:
        ai = AIResponder()
        ai.enabled = True
        ai._client = _FakeClient('{"reply":"ok","action":"delete_all","args":{}}')
        response = ai.respond("test", {"active_rental_count": 1})
        self.assertIsNotNone(response)
        self.assertEqual(response.action, "none")


class TestAILiveEval(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv("AI_EVAL_LIVE", "").lower() not in {"1", "true", "yes"}:
            raise unittest.SkipTest("AI_EVAL_LIVE not enabled")
        cls.ai = get_ai_responder()
        if not cls.ai.enabled:
            raise unittest.SkipTest("AI is not enabled or missing API key")

    def test_eval_cases(self) -> None:
        cases_path = Path(__file__).parent / "ai_eval_cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case.get("name")):
                response = self.ai.respond(case["message"], case["context"])
                self.assertIsNotNone(response)
                self.assertEqual(response.action, case["expect_action"])

