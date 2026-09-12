"""Focused tests for the Coach's provider-neutral Bedrock Converse adapter."""

import base64
import importlib.util
import os
import sys
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
COACH_PATH = os.path.join(ROOT, "functions", "coach", "app.py")


def _load_coach(monkeypatch):
    monkeypatch.setenv("COACH_MODEL_ID", "us.openai.gpt-5.6-sol")
    monkeypatch.setenv("COACH_REASONING_EFFORT", "low")
    for name in list(sys.modules):
        if name == "coach_runtime_under_test" or name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: MagicMock())
    spec = importlib.util.spec_from_file_location("coach_runtime_under_test", COACH_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["coach_runtime_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _drain(generator):
    pieces = []
    while True:
        try:
            pieces.append(next(generator))
        except StopIteration as done:
            return pieces, done.value


def test_converse_configuration_and_frontend_message_conversion(monkeypatch):
    coach = _load_coach(monkeypatch)

    image_bytes = b"small-image"
    messages = coach._to_bedrock_messages([
        {
            "from": "me",
            "text": "check this",
            "images": [{
                "mediaType": "image/png",
                "base64": base64.b64encode(image_bytes).decode("ascii"),
            }],
        }
    ])

    assert coach.MODEL_ID == "us.openai.gpt-5.6-sol"
    assert coach.REASONING_EFFORT == "low"
    assert messages == [{
        "role": "user",
        "content": [
            {"image": {"format": "png", "source": {"bytes": image_bytes}}},
            {"text": "check this"},
        ],
    }]
    assert all("toolSpec" in item for item in coach.CONVERSE_TOOL_CONFIG["tools"])


def test_stream_round_emits_text_with_low_reasoning(monkeypatch):
    coach = _load_coach(monkeypatch)
    fake_bedrock = MagicMock()
    fake_bedrock.converse_stream.return_value = {"stream": [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Ready"}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]}
    coach.bedrock = fake_bedrock

    pieces, result = _drain(coach._stream_model_round(
        [{"role": "user", "content": [{"text": "status"}]}],
        "coach system",
    ))

    assert pieces == ["Ready"]
    assert result == ([{"text": "Ready"}], "end_turn")
    kwargs = fake_bedrock.converse_stream.call_args.kwargs
    assert kwargs["modelId"] == "us.openai.gpt-5.6-sol"
    assert kwargs["inferenceConfig"] == {"maxTokens": 1024}
    assert kwargs["additionalModelRequestFields"] == {"reasoning": {"effort": "low"}}
    assert kwargs["system"] == [{"text": "coach system"}]


def test_stream_round_preserves_reasoning_and_tool_call(monkeypatch):
    coach = _load_coach(monkeypatch)
    fake_bedrock = MagicMock()
    fake_bedrock.converse_stream.return_value = {"stream": [
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {
            "reasoningContent": {"text": "brief", "signature": "sig"}
        }}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {
            "toolUse": {"toolUseId": "tool-1", "name": "get_recent_meals"}
        }}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {
            "toolUse": {"input": '{"days":'}
        }}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {
            "toolUse": {"input": "2}"}
        }}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]}
    coach.bedrock = fake_bedrock

    pieces, result = _drain(coach._stream_model_round(
        [{"role": "user", "content": [{"text": "recent meals"}]}],
        "coach system",
    ))

    content, stop_reason = result
    assert pieces == []
    assert stop_reason == "tool_use"
    assert content[0] == {
        "reasoningContent": {
            "reasoningText": {"text": "brief", "signature": "sig"}
        }
    }
    assert content[1] == {
        "toolUse": {
            "toolUseId": "tool-1",
            "name": "get_recent_meals",
            "input": {"days": 2},
        }
    }


def test_coach_endpoint_completes_tool_round_and_persists_visible_text(monkeypatch):
    from fastapi.testclient import TestClient

    coach = _load_coach(monkeypatch)
    thread = {"conversation_id": "conv_test", "messages": []}
    persisted = MagicMock()
    calls = []

    coach.require_api_key = lambda _key: None
    coach.build_system_prompt = lambda _snapshot: "coach system"
    coach.resolve_thread = lambda _conversation_id: thread
    coach.messages_for_bedrock = lambda _thread: []
    coach._persist_turn = persisted
    coach._feedback_trailer = lambda _message_id: "[feedback]"

    def fake_execute_tool(name, args):
        assert name == "get_recent_meals"
        assert args == {"days": 2}
        return {"meals": [], "days": 2}

    coach._execute_tool = fake_execute_tool

    def fake_stream_round(history, system_prompt):
        calls.append((history, system_prompt))
        if len(calls) == 1:
            return ([
                {
                    "reasoningContent": {
                        "reasoningText": {"text": "brief", "signature": "sig"}
                    }
                },
                {
                    "toolUse": {
                        "toolUseId": "tool-1",
                        "name": "get_recent_meals",
                        "input": {"days": 2},
                    }
                },
            ], "tool_use")

        yield "No recent meals."
        return ([{"text": "No recent meals."}], "end_turn")

    coach._stream_model_round = fake_stream_round

    response = TestClient(coach.app).post(
        "/api/coach",
        json={"messages": [{"from": "me", "text": "Show recent meals."}]},
    )

    assert response.status_code == 200
    assert response.text == "No recent meals.[feedback]"
    assert len(calls) == 2
    second_history = calls[1][0]
    assert second_history[1]["content"][0]["reasoningContent"]["reasoningText"]["signature"] == "sig"
    assert second_history[1]["content"][1]["toolUse"]["toolUseId"] == "tool-1"
    assert second_history[2] == {
        "role": "user",
        "content": [{
            "toolResult": {
                "toolUseId": "tool-1",
                "content": [{"json": {"meals": [], "days": 2}}],
            }
        }],
    }
    assert persisted.call_count == 1
    assert persisted.call_args.args[2] == ["No recent meals."]
