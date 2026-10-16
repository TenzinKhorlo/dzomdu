import json

import httpx
import pytest

from dzomdu.config import LLMConfig
from dzomdu.llm.client import LLMClient, LLMError, extract_json
from dzomdu.llm.schema import ActionItem
from dzomdu.llm.summarize import chunk_lines, summarize
from dzomdu.models import Turn


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('<think>hmm {"no": 1}</think>\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Here you go: {"a": "brace } in string", "b": [1]} thanks') == {
        "a": "brace } in string",
        "b": [1],
    }
    with pytest.raises(LLMError):
        extract_json("no json here")


def _client(handler, **cfg) -> LLMClient:
    return LLMClient(LLMConfig(**cfg), http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_ollama_payload_and_think_fallback():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if "think" in payload:
            return httpx.Response(400, json={"error": "model does not support thinking"})
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    client = _client(handler, model="gemma3:12b", num_ctx=8192)
    assert client.chat_json("sys", "user", {"type": "object"}) == {"ok": True}
    assert seen[0]["options"] == {"temperature": 0.2, "num_ctx": 8192}
    assert seen[0]["format"] == {"type": "object"} and seen[0]["think"] is False
    assert "think" not in seen[1]


def test_openai_falls_back_when_json_schema_unsupported():
    formats = []

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        formats.append(payload.get("response_format", {}).get("type"))
        if formats[-1] == "json_schema":
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}]})

    client = _client(handler, api="openai", base_url="http://localhost:8080/v1")
    assert client.chat_json("s", "u", {"type": "object"}) == {"x": 1}
    assert formats == ["json_schema", "json_object"]


def test_retry_on_invalid_json_then_error():
    replies = iter(["not json", '{"fixed": 1}'])

    def handler(request):
        return httpx.Response(200, json={"message": {"content": next(replies)}})

    assert _client(handler).chat_json("s", "u", {}) == {"fixed": 1}

    def bad(request):
        return httpx.Response(200, json={"message": {"content": "still not json"}})

    with pytest.raises(LLMError):
        _client(bad).chat_json("s", "u", {})


def test_unreachable_server_raises_llm_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="Cannot reach"):
        _client(handler).chat([{"role": "user", "content": "hi"}])
    ok, detail = _client(handler).ping()
    assert not ok and "not reachable" in detail


def test_chunking_respects_budget():
    lines = ["x" * 400] * 10  # ~100 tokens each
    chunks = chunk_lines(lines, max_tokens=250)
    assert [len(c) for c in chunks] == [2, 2, 2, 2, 2]
    assert chunk_lines(["x" * 4000], max_tokens=10) == [["x" * 4000]]


def test_map_reduce_summary():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        system, user = payload["messages"][0]["content"], payload["messages"][1]["content"]
        calls.append(user)
        if system.startswith("You are given structured notes"):
            body = {
                "summary": "Merged.",
                "decisions": [{"decision": "Go", "source_turns": ["t1", "t3", "t42"]}],
            }
        else:
            body = {"summary": "Part.", "decisions": []}
        return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

    turns = [Turn(f"t{i}", "S0", i * 10.0, i * 10.0 + 5, "word " * 200) for i in range(1, 5)]
    notes = summarize(_client(handler), turns, lambda s: "Alice", max_chunk_tokens=600)
    assert len(calls) == 3  # two parts + merge
    assert "Transcript (part 1 of 2)" in calls[0]
    assert "## Partial notes" in calls[2]
    assert notes.summary == "Merged."
    assert notes.decisions[0].source_turns == ["t1", "t3"]  # t42 does not exist


def test_empty_meeting_needs_no_llm():
    def handler(request):  # pragma: no cover
        raise AssertionError("should not be called")

    assert "No speech" in summarize(_client(handler), [], str).summary


def test_cited_topic_point_objects_keep_text_and_valid_citations():
    body = {
        "summary": "The team reviewed deployment.",
        "topics": [{
            "title": "Deployment",
            "points": [
                {"text": "Deploy two agents.", "source_turns": ["t1", "t999"]},
                "Measure productivity.",
                {"text": "Report the results.", "source_turns": ["t2", "t1"]},
            ],
            "source_turns": ["t2"],
        }],
    }
    client = _client(lambda _: httpx.Response(200, json={
        "message": {"content": json.dumps(body)},
    }))
    turns = [Turn("t1", "S0", 0, 5, "Deploy two agents."),
             Turn("t2", "S0", 5, 10, "Measure productivity and report results.")]
    notes = summarize(client, turns, str)
    assert notes.topics[0].points == [
        "Deploy two agents.", "Measure productivity.", "Report the results.",
    ]
    assert notes.topics[0].source_turns == ["t2", "t1"]


def test_schema_validation_retries_with_correction_instructions():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload["messages"][-1]["content"])
        body = {"summary": ["Wrong shape"]} if len(seen) == 1 else {"summary": "Corrected."}
        return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

    notes = summarize(_client(handler), [Turn("t1", "S0", 0, 5, "Discuss the plan.")], str)
    assert notes.summary == "Corrected."
    assert len(seen) == 2
    assert "previous reply did not match" in seen[1]
    assert "summary: Input should be a valid string" in seen[1]
    assert "Discuss the plan." in seen[1]


@pytest.mark.parametrize("alternate", ["action", "action_item", "description", "text"])
def test_action_task_alias_keeps_owner_deadline_and_citations(alternate):
    body = {
        "summary": "The team agreed to draft the plan.",
        "action_items": [{alternate: "Draft the plan", "owner": "Alice",
                          "due": "next Tuesday", "source_turns": ["t1", "t99"]}],
    }
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

    notes = summarize(
        _client(handler), [Turn("t1", "S0", 0, 5, "I'll draft the plan next Tuesday.")],
        lambda _: "Alice",
    )
    item = notes.action_items[0]
    assert item.task == "Draft the plan" and item.owner == "Alice"
    assert item.due == "next Tuesday" and item.source_turns == ["t1"]
    assert len(payloads) == 1
    prompt = payloads[0]["messages"][-1]["content"]
    assert "## Required JSON schema" in prompt
    assert '"required": ["task"]' in prompt


@pytest.mark.parametrize("item", [
    {"owner": "Alice"},
    {"task": ""},
    {"task": "   "},
    {"action": ""},
    {"text": {"description": "Nested content"}},
    {"action": "Send the plan", "description": "Cancel the plan"},
])
def test_missing_or_ambiguous_task_is_not_invented(item):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ActionItem.model_validate(item)


@pytest.mark.parametrize("point", [{"unknown": "bad"}, {"text": 42},
                                   {"text": "A point", "source_turns": [42]}])
def test_unrecognised_point_objects_still_fail_validation_after_one_retry(point):
    calls = []

    def handler(request):
        calls.append(request)
        body = {"summary": "Summary.", "topics": [{"title": "Plan", "points": [point]}]}
        return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

    with pytest.raises(LLMError, match="topics.0.points.0"):
        summarize(_client(handler), [Turn("t1", "S0", 0, 5, "Discuss the plan.")], str)
    assert len(calls) == 2


def test_openai_stream_yields_content_without_reasoning():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            content=(
                b": keepalive\n\n"
                b'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    client = _client(handler, api="openai", base_url="http://localhost:8080/v1")
    assert list(client.chat_stream([{"role": "user", "content": "Hi"}])) == ["Hello ", "world"]


@pytest.mark.parametrize(
    "content",
    [
        b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"Partial"},"finish_reason":"length"}]}\n\n',
        b"data: malformed\n\n",
        b'data: {"error":{"message":"unavailable"}}\n\n',
    ],
)
def test_incomplete_or_failed_openai_stream_raises(content):
    client = _client(lambda request: httpx.Response(200, content=content), api="openai")
    with pytest.raises(LLMError):
        list(client.chat_stream([{"role": "user", "content": "Hi"}]))


def test_ollama_stream_retries_unsupported_think_flag():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if "think" in payload:
            return httpx.Response(400, json={"error": "think is unsupported"})
        return httpx.Response(200, content=b'{"message":{"content":"Answer"},"done":true}\n')

    assert list(_client(handler).chat_stream([{"role": "user", "content": "Hi"}])) == ["Answer"]
    assert seen[0]["stream"] and "think" not in seen[1]
