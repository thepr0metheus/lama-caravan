#!/usr/bin/env python3
"""What an Anthropic answer says it used reaches the caravan whole: the input, the cache and the output (1.3.585).

On 2026-10-18 the owner held the Routing card of the Anthropic account against the Console of the provider. The card said "12 req · 7.2K tok ≈ $0"
and "≈ $200 left of $200"; the Console showed $1.22 spent. The stream's translation read `usage` only from `message_delta` — where Anthropic puts
the output — and wrote `prompt_tokens: 0`. The input is in `message_start`: `input_tokens` (the part not served from the cache),
`cache_creation_input_tokens` and `cache_read_input_tokens`. A streamed answer was counted by its output alone.

A stream that is cut (1.3.586). The usage rides the last chunk, and a stream the client cuts off or the provider drops never gets there: its input,
billed all the same, was recorded as 0. The translator takes the caller's `AnthropicUsage`, which holds what the answer has said by ANY moment — the
input from `message_start` the moment it is read, the output as far as it was told — and the handler falls back on it where no chunk carried the
usage. Pinned here: the object after each chunk of a stream that is left unfinished, a stream that ends right after `message_start`, and the default
(no object given: as before). The handler's side is test_proxy_forward.py (a client that leaves in the middle of a stream).

Pinned, by value, each with its negative: what counts as a token count (a number, a number written as text or 7.0; not a word, a boolean, a
negative); how the figures fold (the largest seen, since the counts are cumulative: a delta that repeats the input does not add it twice, and a
smaller later figure does not take anything back); the OpenAI shape (all the input as `prompt_tokens`, the cached part and the part written named
only where there is one); the stream end to end (message_start + deltas, the older shape with output alone, the newer delta that repeats the input,
no usage at all, the input with a delta that names no usage); and the whole answer (with the cache, without it, with nothing, with junk).

No sockets: the translators run on lists of lines.

Run: python3 scripts/test_anthropic_usage.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.proxy.translate import AnthropicUsage, _anthropic_to_completions_json, _iter_anthropic_as_completions_sse  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def usage_of(*parts):
    used = AnthropicUsage()
    for part in parts:
        used.take(part)
    return used


def sse_lines(events):
    """The lines of an Anthropic stream for these (event name, payload) pairs, as the provider's socket yields them."""
    for name, payload in events:
        yield f"event: {name}\n".encode()
        yield ("data: " + json.dumps(payload) + "\n").encode()
        yield b"\n"


def stream(events):
    """The chunks the translator yields for these (event name, payload) pairs, as dicts, and whether it ended with [DONE]."""
    out = b"".join(_iter_anthropic_as_completions_sse(sse_lines(events), "chatcmpl-x", "claude-test"))
    frames = [f for f in out.split(b"\n\n") if f.startswith(b"data: ")]
    chunks = [json.loads(f[6:]) for f in frames if b"[DONE]" not in f]
    return chunks, out.endswith(b"data: [DONE]\n\n")


START = ("message_start", {"type": "message_start", "message": {"usage": {
    "input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 1}}})
TEXT = ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}})
STOP = ("message_stop", {"type": "message_stop"})


def delta(usage=None, stop="end_turn"):
    payload = {"type": "message_delta", "delta": {"stop_reason": stop}}
    if usage is not None:
        payload["usage"] = usage
    return ("message_delta", payload)


def final_usage(events):
    chunks, _ = stream(events)
    return [c["usage"] for c in chunks if "usage" in c]


def test_what_is_a_count():
    print("what counts as a token count:")
    got = [AnthropicUsage.count(v) for v in (7, 7.0, "7", " 7 ", 1.9, 0, -5, True, False, None, "abc", "7.5", float("nan"), float("inf"), [], {})]
    check(got == [7, 7, 7, 7, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
          f"a number, one written as 7.0 or as text, counts as the whole number it is (as the translation read it before); a word, a boolean, a negative, "
          f"nothing, nan, infinity and a container count as 0 (got {got})")


def test_the_fold():
    print("how the figures fold:")
    used = usage_of({"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 1}, {"output_tokens": 2})
    check((used.prompt, used.completion) == (2112, 2), f"input + cache written + cache read is the prompt (2112); the output is the delta's (got {used.prompt}, {used.completion})")
    again = usage_of({"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 1},
                     {"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 2})
    check((again.prompt, again.completion) == (2112, 2),
          f"a delta that repeats the input (the newer API) does not add it twice: still 2112, not 4224 (got {again.prompt})")
    check(usage_of({"output_tokens": 50}, {"output_tokens": 10}).completion == 50,
          "negative: a smaller figure that comes later takes nothing back — the counts are cumulative, the largest stands")
    check(usage_of({"input_tokens": 5}, {"input_tokens": 9}).prompt == 9, "a larger one that comes later replaces it")
    check(usage_of(None, "x", [], 7, {"output_tokens": "x"}, {"input_tokens": None}).seen == dict.fromkeys(AnthropicUsage.FIELDS, 0),
          "negative: no usage, a text, a list, a number, a count that is a word: nothing is taken, nothing crashes")
    check((usage_of().known(), usage_of({"output_tokens": 3}).known(), usage_of({"input_tokens": 3}).known(), usage_of({"cache_read_input_tokens": 3}).known())
          == (False, True, True, True),
          "known: nothing is not known; an output alone, an input alone, a cache read alone are")
    check(usage_of({"output_tokens": 0, "input_tokens": 0}).known() is False, "boundary: figures that are all zero are not known either — the answer said nothing")


def test_the_openai_shape():
    print("the OpenAI shape:")
    check(usage_of({"input_tokens": 3, "output_tokens": 2}).openai() == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
          "no cache: three numbers and nothing else — a client that reads them sees what it always saw")
    got = usage_of({"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 2}).openai()
    check(got == {"prompt_tokens": 2112, "completion_tokens": 2, "total_tokens": 2114, "prompt_tokens_details": {"cached_tokens": 2000},
                  "cache_creation_input_tokens": 100},
          f"with a cache: ALL the input is prompt_tokens (2112), the cached part is named where OpenAI names it, the part written beside them (got {got})")
    only_read = usage_of({"input_tokens": 1, "cache_read_input_tokens": 9, "output_tokens": 1}).openai()
    check("prompt_tokens_details" in only_read and "cache_creation_input_tokens" not in only_read,
          "negative: only a read — no 'written' field; the field is there only where the cache was used")
    only_written = usage_of({"input_tokens": 1, "cache_creation_input_tokens": 9, "output_tokens": 1}).openai()
    check("cache_creation_input_tokens" in only_written and "prompt_tokens_details" not in only_written,
          "negative: only a write — no 'cached' field")
    check(usage_of().openai() == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "nothing taken: zeros, no cache fields")


def test_the_stream():
    print("the stream, end to end:")
    both = final_usage([START, TEXT, delta({"output_tokens": 2}), STOP])
    check(both == [{"prompt_tokens": 2112, "completion_tokens": 2, "total_tokens": 2114, "prompt_tokens_details": {"cached_tokens": 2000},
                    "cache_creation_input_tokens": 100}],
          f"message_start names the input, message_delta the output: ONE usage in the last chunk, prompt 2112 — it was 0 before 1.3.585 (got {both})")
    chunks, done = stream([START, TEXT, delta({"output_tokens": 2}), STOP])
    check(done and [c["choices"][0]["finish_reason"] for c in chunks if "usage" in c] == ["stop"] and "usage" not in chunks[0],
          "the usage rides the chunk that carries the stop reason, not the first one; the stream ends with [DONE]")
    old = final_usage([TEXT, delta({"output_tokens": 2}), STOP])
    check(old == [{"prompt_tokens": 0, "completion_tokens": 2, "total_tokens": 2}],
          f"negative: an answer with no message_start says what it did before — the output alone, prompt 0, no cache fields (got {old})")
    repeated = final_usage([START, TEXT, delta({"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 2}), STOP])
    check(repeated and repeated[0]["prompt_tokens"] == 2112 and repeated[0]["total_tokens"] == 2114,
          f"the newer API repeats the input in the delta: counted once (got {repeated})")
    nothing = final_usage([TEXT, delta(), STOP])
    check(nothing == [], f"negative: an answer that says nothing of its use has no usage in the chunk — as before, not zeros that read as 'used nothing' (got {nothing})")
    quiet_delta = final_usage([START, TEXT, delta(), STOP])
    check(quiet_delta and quiet_delta[0]["prompt_tokens"] == 2112 and quiet_delta[0]["completion_tokens"] == 1,
          f"a delta that names no usage still gives the input of message_start, and the output it had then (got {quiet_delta})")
    input_only = final_usage([("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 5}}}), TEXT, delta(), STOP])
    check(input_only == [{"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5}],
          f"an input and no output yet is known, too: the usage is there, the output 0 (got {input_only})")
    junk_start = final_usage([("message_start", {"type": "message_start", "message": "x"}), TEXT, delta({"output_tokens": 2}), STOP])
    check(junk_start == [{"prompt_tokens": 0, "completion_tokens": 2, "total_tokens": 2}], "a message_start with no usage object is nothing to take: no crash")
    tools = stream([START, ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}}), STOP])[0]
    check([c["choices"][0]["finish_reason"] for c in tools if "usage" in c] == ["tool_calls"], "a stop for a tool call is still a tool call, usage or not")


def test_a_stream_that_is_cut():
    print("a stream that is cut:")
    used = AnthropicUsage()
    it = _iter_anthropic_as_completions_sse(sse_lines([START, TEXT, TEXT, delta({"output_tokens": 9}), STOP]), "chatcmpl-x", "claude-test", used=used)
    next(it)
    check((used.prompt, used.completion, used.known()) == (0, 0, False),
          "the opening chunk comes before anything of the provider's is read: the caller's object knows nothing yet")
    next(it)
    check((used.prompt, used.completion, used.known()) == (2112, 1, True),
          f"the first text chunk: message_start has been read — the input is 2112 (billed whatever happens next), the output is what was told so far, 1 (got {used.prompt}, {used.completion})")
    it.close()
    check((used.prompt, used.completion) == (2112, 1), "the client leaves here: the object still says it, and the unread rest of the stream adds nothing")
    ended = AnthropicUsage()
    chunks = list(_iter_anthropic_as_completions_sse(sse_lines([START]), "chatcmpl-x", "claude-test", used=ended))
    check(ended.prompt == 2112 and not any(b'"usage"' in c for c in chunks),
          "negative: a stream the provider drops right after message_start has no chunk with usage — and the object has the input all the same")
    quiet = AnthropicUsage()
    list(_iter_anthropic_as_completions_sse(sse_lines([TEXT, STOP]), "chatcmpl-x", "claude-test", used=quiet))
    check(quiet.known() is False, "negative: a stream that never named its use leaves the object as it was: not known — nothing to record")
    default = list(_iter_anthropic_as_completions_sse(sse_lines([START, TEXT, delta({"output_tokens": 2}), STOP]), "chatcmpl-x", "claude-test"))
    check(any(b'"prompt_tokens":2112' in c for c in default), "no object given: the translator keeps its own, as before — the last chunk still says the usage")
    shared = AnthropicUsage()
    last = [json.loads(c[6:]) for c in _iter_anthropic_as_completions_sse(sse_lines([START, TEXT, delta({"output_tokens": 2}), STOP]), "chatcmpl-x", "claude-test", used=shared)
            if c.startswith(b"data: {") and b'"usage"' in c]
    check(last and last[0]["usage"]["prompt_tokens"] == 2112 == shared.prompt and shared.completion == 2,
          "the object the caller gave is the one the last chunk is made from: the two cannot disagree")


def test_the_whole_answer():
    print("the whole answer:")

    def whole(usage):
        body = {"content": [{"type": "text", "text": "hello"}]}
        if usage is not None:
            body["usage"] = usage
        return json.loads(_anthropic_to_completions_json(json.dumps(body).encode(), "chatcmpl-x", "claude-test"))["usage"]
    check(whole({"input_tokens": 3, "output_tokens": 2}) == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
          "without a cache: input 3, output 2, total 5 — as it was")
    check(whole({"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 2000, "output_tokens": 7})
          == {"prompt_tokens": 2112, "completion_tokens": 7, "total_tokens": 2119, "prompt_tokens_details": {"cached_tokens": 2000}, "cache_creation_input_tokens": 100},
          "with a cache: all the input is the prompt (2112), the cached and the written part named — before 1.3.585 only the plain 12 was counted")
    check(whole(None) == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "negative: no usage in the answer — zeros, as before")
    check(whole("x") == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "negative: a usage that is no object — zeros, no crash")
    check(whole({"input_tokens": 3.0, "output_tokens": "2"}) == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
          "boundary: counts written as 3.0 and \"2\" count, as they did")
    check(_anthropic_to_completions_json(b"not json", "c", "m") == b"not json", "negative: an answer that is no JSON goes through as it is")


def main():
    for fn in (test_what_is_a_count, test_the_fold, test_the_openai_shape, test_the_stream, test_a_stream_that_is_cut, test_the_whole_answer):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} crashed: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\nanthropic usage OK: the input, the cache and the output reach the journal whole")


if __name__ == "__main__":
    main()
