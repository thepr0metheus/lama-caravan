"""Protocol translation: OpenAI chat-completions <-> Responses API and
Anthropic Messages, both buffered and SSE-streamed, plus proxy error taxonomy."""
import base64 as _b64
import json
import socket
import time

from caravan.common.chat_levers import ChatLevers


def model_named(body, model):
    """The request with the model the caravan chose in it.

    One engine next to the cells (Ollama, LM Studio) serves many models
    behind one port and picks the one a request names; the router's output
    names the model it routes to. A provider behind a pool's row is asked for
    the row's model. Set whenever the body is a JSON object — added when the
    client sent none (a key of the entry calls its pool and need not name a
    model: before 1.3.486 a cloud request without one reached the provider
    without one, and was refused there), replaced when it named another (its
    own name for the port or the pool is not the provider's). Any other body
    goes as it came: the same bytes, so the caller can tell nothing changed."""
    if not body or not model:
        return body
    try:
        payload = json.loads(body)
    except Exception:
        return body
    if not isinstance(payload, dict) or payload.get("model") == model:
        return body
    payload["model"] = model
    return json.dumps(payload).encode("utf-8")

def _extract_chatgpt_account_id(token):
    """Extract chatgpt_account_id claim from an OpenAI JWT access token."""
    try:
        parts = token.split(".")
        pad = "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(_b64.urlsafe_b64decode(parts[1] + pad))
        return payload["https://api.openai.com/auth"]["chatgpt_account_id"]
    except Exception:
        return None

def _chat_to_responses_body(body_bytes, override_model=None):
    """Convert an OpenAI chat/completions request body to the Responses API format
    used by chatgpt.com/backend-api/codex/responses.
    Returns (new_body_bytes, model_name_used).
    """
    if not body_bytes:
        # Empty body — create minimal valid request
        model_name = override_model or "gpt-5.4-mini"
        body = {"model": model_name, "store": False, "stream": True,
                "instructions": "You are a helpful assistant.", "input": []}
        return json.dumps(body).encode("utf-8"), model_name
    try:
        payload = json.loads(body_bytes)
    except Exception:
        return body_bytes, None

    messages = payload.get("messages") or []
    instructions = "You are a helpful assistant."
    input_msgs = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "system":
            if isinstance(content, str):
                instructions = content
            elif isinstance(content, list):
                instructions = "\n".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
        elif role == "user":
            if isinstance(content, str):
                input_msgs.append({
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}],
                })
            elif isinstance(content, list):
                parts = []
                for p in content:
                    if p.get("type") == "text":
                        parts.append({"type": "input_text", "text": p.get("text", "")})
                    elif p.get("type") == "image_url":
                        image = p.get("image_url") or {}
                        url = image.get("url", "") if isinstance(image, dict) else ""
                        parts.append({"type": "input_image", "detail": ChatLevers.detail(image), "image_url": url})
                if parts:
                    input_msgs.append({"role": "user", "content": parts})
        elif role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                if content:
                    text = content if isinstance(content, str) else str(content)
                    input_msgs.append({
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    })
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    tc_id = tc.get("id", "")
                    fc_id = tc_id if tc_id.startswith("fc") else f"fc_{tc_id}"
                    input_msgs.append({
                        "type": "function_call",
                        "id": fc_id,
                        "call_id": tc_id,
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", ""),
                    })
            elif content:
                text = content if isinstance(content, str) else str(content)
                input_msgs.append({
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                })
        elif role == "tool":
            result = content if isinstance(content, str) else json.dumps(content)
            input_msgs.append({
                "type": "function_call_output",
                "call_id": msg.get("tool_call_id", ""),
                "output": result,
            })

    model_name = override_model or payload.get("model") or "gpt-5.4-mini"
    body = {
        "model": model_name,
        "store": False,
        "stream": True,
        "instructions": instructions,
        "input": input_msgs,
        # The client's reasoning_effort and verbosity, said the Responses way (ChatLevers):
        # "text" always, "reasoning" when the client asked for an effort.
        **ChatLevers.for_responses(payload),
        "include": [],
        "tool_choice": payload.get("tool_choice", "auto"),
        "parallel_tool_calls": payload.get("parallel_tool_calls", True),
    }
    if payload.get("tools"):
        # Convert from Chat Completions format {"type":"function","function":{...}}
        # to Responses API format {"type":"function","name":"...","description":"...","parameters":{...}}
        converted_tools = []
        for t in payload["tools"]:
            if not isinstance(t, dict):
                continue
            if t.get("type") == "function" and isinstance(t.get("function"), dict):
                fn = t["function"]
                tool = {"type": "function", "name": fn.get("name", "")}
                if fn.get("description"):
                    tool["description"] = fn["description"]
                if fn.get("parameters"):
                    tool["parameters"] = fn["parameters"]
                if fn.get("strict") is not None:
                    tool["strict"] = fn["strict"]
                converted_tools.append(tool)
            else:
                # Already in Responses format or unknown — pass through
                converted_tools.append(t)
        body["tools"] = converted_tools
    # Note: chatgpt.com/backend-api/codex/responses does NOT support temperature,
    # top_p, frequency_penalty, presence_penalty, max_tokens — omit them.
    return json.dumps(body).encode("utf-8"), model_name

def is_responses_request(path, body_bytes):
    """A client already speaking the Responses API: the path says so, or the body
    carries `input` and no `messages`. Codex CLI is the first such client — it
    talks Responses only, and the chat translator turned its `input` into an
    empty list, which the codex backend refused with "input must be provided"."""
    if str(path or "").rstrip("/").endswith("/responses"):
        return True
    try:
        payload = json.loads(body_bytes or b"")
    except Exception:
        return False
    return isinstance(payload, dict) and "input" in payload and "messages" not in payload


def _responses_passthrough_body(body_bytes, override_model=None):
    """A Responses-API request bound for chatgpt.com/backend-api/codex/responses.

    The body goes through as the client wrote it — `input`, `instructions`,
    `tools`, `reasoning`, `text` are the client's — with the three fields the
    subscription backend dictates: the block's model when the block rewrites,
    `store: false` (the backend keeps nothing) and `stream: true` (it only
    streams; a client that asked for a buffered answer gets it assembled from
    the stream). Returns (new_body_bytes, model_name, client_wants_stream)."""
    try:
        payload = json.loads(body_bytes or b"")
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {"input": []}
    model_name = override_model or payload.get("model") or "gpt-5.4-mini"
    client_stream = bool(payload.get("stream", True))
    payload["model"] = model_name
    payload["store"] = False
    payload["stream"] = True
    # The public Responses API takes `input` as a bare string; the subscription
    # backend answers "Input must be a list" to that. One user turn, then.
    if isinstance(payload.get("input"), str):
        payload["input"] = [{"role": "user", "content": [{"type": "input_text", "text": payload["input"]}]}]
    return json.dumps(payload).encode("utf-8"), model_name, client_stream


def iter_responses_passthrough(upstream, summary, keep_response=False):
    """Relay a Responses-API SSE stream untouched, keeping the same tallies the
    translator keeps (delta text, usage, done) in `summary` for the journal.
    `keep_response` stores the final `response` object too — only for a client
    that asked for a buffered answer; the journal must not carry the output."""
    done_items = []
    for raw in upstream:
        yield raw
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except Exception:
            continue
        etype = ev.get("type", "")
        summary["events"] = summary.get("events", 0) + 1
        if etype == "response.output_text.delta":
            summary["deltaTextChars"] = summary.get("deltaTextChars", 0) + len(str(ev.get("delta") or ""))
        elif etype == "response.output_item.done" and isinstance(ev.get("item"), dict):
            done_items.append(ev["item"])
        elif etype == "response.completed":
            response_obj = ev.get("response") or {}
            # The subscription backend's final response carries no `output` —
            # the items only ever arrive as output_item.done events. A buffered
            # client would get a completed response with nothing in it.
            if not response_obj.get("output") and done_items:
                response_obj = dict(response_obj, output=done_items)
            usage = response_obj.get("usage") or {}
            if usage:
                summary["usage"] = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                }
            summary["finishReasons"] = ["tool_calls" if any(
                isinstance(item, dict) and item.get("type") == "function_call"
                for item in (response_obj.get("output") or [])) else "stop"]
            summary["done"] = True
            if keep_response:
                summary["response"] = response_obj


def _iter_responses_as_completions_sse(upstream, completion_id, model_name):
    """Translate OpenAI Responses API SSE stream into chat/completions SSE format.
    Yields bytes chunks ready to write directly to the client socket.
    """
    ts = int(time.time())
    # Initial role delta
    initial = {
        "id": completion_id, "object": "chat.completion.chunk",
        "created": ts, "model": model_name,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    yield b"data: " + json.dumps(initial, separators=(",", ":")).encode() + b"\n\n"

    tc_output_index_to_chat_index = {}
    finish_reason = "stop"

    for raw in upstream:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            ev = json.loads(data_str)
        except Exception:
            continue

        etype = ev.get("type", "")

        if etype == "response.output_text.delta":
            chunk = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_name,
                "choices": [{"index": 0, "delta": {"content": ev.get("delta", "")}, "finish_reason": None}],
            }
            yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"

        elif etype == "response.output_item.added":
            item = ev.get("item", {})
            if item.get("type") == "function_call":
                output_index = ev.get("output_index", 0)
                chat_index = len(tc_output_index_to_chat_index)
                tc_output_index_to_chat_index[output_index] = chat_index
                chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": ts, "model": model_name,
                    "choices": [{"index": 0, "delta": {
                        "tool_calls": [{
                            "index": chat_index,
                            "id": item.get("call_id") or item.get("id", ""),
                            "type": "function",
                            "function": {"name": item.get("name", ""), "arguments": ""},
                        }]
                    }, "finish_reason": None}],
                }
                yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"

        elif etype == "response.function_call_arguments.delta":
            output_index = ev.get("output_index", 0)
            chat_index = tc_output_index_to_chat_index.get(output_index, output_index)
            chunk = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_name,
                "choices": [{"index": 0, "delta": {
                    "tool_calls": [{"index": chat_index, "function": {"arguments": ev.get("delta", "")}}]
                }, "finish_reason": None}],
            }
            yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"

        elif etype == "response.completed":
            response_obj = ev.get("response", {})
            output = response_obj.get("output") or []
            if any(item.get("type") == "function_call" for item in output):
                finish_reason = "tool_calls"
            usage = response_obj.get("usage") or {}
            final = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }
            if usage:
                final["usage"] = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                }
            yield b"data: " + json.dumps(final, separators=(",", ":")).encode() + b"\n\n"
            break

    yield b"data: [DONE]\n\n"

class ChunkFold:
    """Chat completion chunks folded into the one chat completion they stream.

    A client that did not ask for a stream reads one JSON answer — OpenAI's
    `stream` defaults to false — while a provider may stream regardless (the
    Codex backend always does). The fold keeps what a client reads: each
    choice's role, text, tool calls (by their index, the arguments joined)
    and finish reason; the answer's id, time and model; and its usage.
    `finished` says whether any choice got its finish reason: a stream cut
    before its last word is no whole answer, and must not be handed out as one.
    """

    def __init__(self):
        self.head = {}
        self.choices = {}
        self.usage = None

    def add(self, chunk):
        """Take one piece of the stream: `data: {…}` lines; [DONE] and anything else pass."""
        for line in bytes(chunk).decode("utf-8", errors="replace").splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if isinstance(event, dict):
                self._event(event)

    def _event(self, event):
        for key in ("id", "created", "model"):
            if key in event and key not in self.head:
                self.head[key] = event[key]
        if isinstance(event.get("usage"), dict):
            self.usage = event["usage"]
        for choice in event.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            slot = self.choices.setdefault(int(choice.get("index") or 0),
                                           {"role": "", "text": [], "calls": {}, "finish": None})
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            if delta.get("role"):
                slot["role"] = str(delta["role"])
            if isinstance(delta.get("content"), str):
                slot["text"].append(delta["content"])
            for call in delta.get("tool_calls") or []:
                if isinstance(call, dict):
                    self._call(slot["calls"], call)
            if choice.get("finish_reason"):
                slot["finish"] = str(choice["finish_reason"])

    @staticmethod
    def _call(calls, part):
        held = calls.setdefault(int(part.get("index") or 0),
                                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if part.get("id"):
            held["id"] = str(part["id"])
        if part.get("type"):
            held["type"] = str(part["type"])
        fn = part.get("function") if isinstance(part.get("function"), dict) else {}
        if fn.get("name"):
            held["function"]["name"] += str(fn["name"])
        if isinstance(fn.get("arguments"), str):
            held["function"]["arguments"] += fn["arguments"]

    def finished(self):
        return any(slot["finish"] for slot in self.choices.values())

    def completion(self):
        """The answer as OpenAI's chat completion object. A message with tool
        calls and no text has `content: null`, as OpenAI's has."""
        choices = []
        for index in sorted(self.choices):
            slot = self.choices[index]
            calls = [slot["calls"][i] for i in sorted(slot["calls"])]
            text = "".join(slot["text"])
            message = {"role": slot["role"] or "assistant", "content": text if (text or not calls) else None}
            if calls:
                message["tool_calls"] = calls
            choices.append({"index": index, "message": message, "logprobs": None,
                            "finish_reason": slot["finish"] or "stop"})
        out = {"id": self.head.get("id", ""), "object": "chat.completion", "created": self.head.get("created", 0),
               "model": self.head.get("model", ""), "choices": choices}
        if self.usage is not None:
            out["usage"] = self.usage
        return out

def _chat_to_anthropic_body(body_bytes, model_override=None):
    """Convert OpenAI chat/completions request to Anthropic Messages API format."""
    if not body_bytes:
        body = {"model": model_override or "claude-opus-4-8", "max_tokens": 4096, "messages": []}
        return json.dumps(body).encode("utf-8")
    try:
        payload = json.loads(body_bytes)
    except Exception:
        return body_bytes
    messages = payload.get("messages") or []
    system_content = None
    anthropic_msgs = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")
        content = msg.get("content") or ""
        if role == "system":
            system_content = content if isinstance(content, str) else "\n".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
            i += 1
            continue
        if role == "tool":
            # Merge consecutive tool results into one user message
            results = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tm = messages[i]
                tc = tm.get("content") or ""
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tm.get("tool_call_id", ""),
                    "content": tc if isinstance(tc, str) else json.dumps(tc),
                })
                i += 1
            anthropic_msgs.append({"role": "user", "content": results})
            continue
        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                blocks = []
                if content:
                    text = content if isinstance(content, str) else str(content)
                    if text:
                        blocks.append({"type": "text", "text": text})
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    args_str = fn.get("arguments", "")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                    except Exception:
                        args = {}
                    blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                                   "name": fn.get("name", ""), "input": args})
                anthropic_msgs.append({"role": "assistant", "content": blocks})
            elif isinstance(content, list):
                blocks = [{"type": "text", "text": p.get("text", "")}
                          for p in content if isinstance(p, dict) and p.get("type") == "text"]
                anthropic_msgs.append({"role": "assistant", "content": blocks or str(content)})
            else:
                anthropic_msgs.append({"role": "assistant", "content": content if isinstance(content, str) else str(content)})
            i += 1
            continue
        if role == "user":
            if isinstance(content, str):
                anthropic_msgs.append({"role": "user", "content": content})
            elif isinstance(content, list):
                blocks = []
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    if p.get("type") == "text":
                        blocks.append({"type": "text", "text": p.get("text", "")})
                    elif p.get("type") == "image_url":
                        url = (p.get("image_url") or {}).get("url", "")
                        if url.startswith("data:"):
                            try:
                                header, data = url.split(",", 1)
                                media_type = header.split(":")[1].split(";")[0]
                            except Exception:
                                media_type, data = "image/jpeg", ""
                            blocks.append({"type": "image",
                                           "source": {"type": "base64", "media_type": media_type, "data": data}})
                        else:
                            blocks.append({"type": "image", "source": {"type": "url", "url": url}})
                anthropic_msgs.append({"role": "user", "content": blocks})
            else:
                anthropic_msgs.append({"role": "user", "content": str(content)})
            i += 1
            continue
        i += 1
    model = model_override or payload.get("model") or "claude-opus-4-8"
    body = {
        "model": model,
        "messages": anthropic_msgs,
        "max_tokens": int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 4096),
        "stream": bool(payload.get("stream", False)),
    }
    if system_content is not None:
        body["system"] = system_content
    if payload.get("temperature") is not None:
        body["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        body["top_p"] = payload["top_p"]
    if payload.get("stop"):
        s = payload["stop"]
        body["stop_sequences"] = [s] if isinstance(s, str) else s
    if payload.get("tools"):
        anthropic_tools = []
        for t in payload["tools"]:
            if not isinstance(t, dict):
                continue
            if t.get("type") == "function" and isinstance(t.get("function"), dict):
                fn = t["function"]
                tool = {"name": fn.get("name", "")}
                if fn.get("description"):
                    tool["description"] = fn["description"]
                tool["input_schema"] = fn.get("parameters") or {"type": "object", "properties": {}}
                anthropic_tools.append(tool)
        if anthropic_tools:
            body["tools"] = anthropic_tools
    if payload.get("tool_choice") is not None:
        tc = payload["tool_choice"]
        if tc == "auto":
            body["tool_choice"] = {"type": "auto"}
        elif tc == "none":
            body["tool_choice"] = {"type": "none"}
        elif tc == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(tc, dict) and tc.get("type") == "function":
            body["tool_choice"] = {"type": "tool", "name": (tc.get("function") or {}).get("name", "")}
    return json.dumps(body).encode("utf-8")

class AnthropicUsage:
    """What an Anthropic response says it used, gathered from where it says it.

    `message_start` carries the input — `input_tokens` (the part not served from the cache), `cache_creation_input_tokens`, `cache_read_input_tokens` —
    and `message_delta` the output so far; newer API versions repeat the input in the delta. OpenAI's `prompt_tokens` is ALL the input, cached or
    not, with the cached part under `prompt_tokens_details.cached_tokens`.

    Until 1.3.585 the stream's translation read only `message_delta` and wrote `prompt_tokens: 0`: a streamed answer of Anthropic was recorded with
    its output alone. The Routing card of 2026-10-18 said "12 req · 7.2K tok ≈ $0" and "≈ $200 left of $200" while the Console showed $1.22 spent
    (the Console counts the whole organization, whatever went around the caravan). And an agent reading `usage` of the stream saw an input of 0.

    The counts are cumulative, so a figure is taken only by being larger than the one before: a delta that repeats the input does not add it twice."""

    FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")

    def __init__(self):
        self.seen = dict.fromkeys(self.FIELDS, 0)

    @staticmethod
    def count(value):
        """A token count as a whole number; 0 for what is no count (missing, a word, a negative, a boolean). A count written as 7.0 or "7"
        is 7, as the translation read it before: a gateway between the caravan and the provider may write it so."""
        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    def take(self, usage):
        """Fold one usage object in (a `message_start`'s, a delta's, a whole response's)."""
        usage = usage if isinstance(usage, dict) else {}
        for name in self.FIELDS:
            self.seen[name] = max(self.seen[name], self.count(usage.get(name)))
        return self

    @property
    def prompt(self):
        return self.seen["input_tokens"] + self.seen["cache_creation_input_tokens"] + self.seen["cache_read_input_tokens"]

    @property
    def completion(self):
        return self.seen["output_tokens"]

    def known(self):
        return self.prompt > 0 or self.completion > 0

    def openai(self):
        """The usage as OpenAI's chat completion says it: all the input as `prompt_tokens`, the cached part and the part written to the cache named."""
        out = {"prompt_tokens": self.prompt, "completion_tokens": self.completion, "total_tokens": self.prompt + self.completion}
        if self.seen["cache_read_input_tokens"]:
            out["prompt_tokens_details"] = {"cached_tokens": self.seen["cache_read_input_tokens"]}
        if self.seen["cache_creation_input_tokens"]:
            out["cache_creation_input_tokens"] = self.seen["cache_creation_input_tokens"]
        return out


def _iter_anthropic_as_completions_sse(upstream, completion_id, model_name, used=None):
    """Translate Anthropic Messages API SSE stream into chat/completions SSE format.

    `used` is the caller's AnthropicUsage, for a caller that wants what the answer has said it used at ANY moment and not only from the last
    chunk, where the usage rides. A stream the client cuts off, or one the provider drops, never reaches `message_delta`; its input is billed
    all the same, and read only from the last chunk it would be recorded as 0 (1.3.586)."""
    ts = int(time.time())
    used = used if used is not None else AnthropicUsage()
    initial = {
        "id": completion_id, "object": "chat.completion.chunk",
        "created": ts, "model": model_name,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    yield b"data: " + json.dumps(initial, separators=(",", ":")).encode() + b"\n\n"
    block_index_to_type = {}
    tc_index_map = {}
    tc_chat_index = 0
    finish_reason = "stop"
    pending_event = None
    for raw in upstream:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("event: "):
            pending_event = line[7:]
            continue
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            ev = json.loads(data_str)
        except Exception:
            continue
        etype = ev.get("type", "") or pending_event or ""
        pending_event = None
        if etype == "message_start":
            message = ev.get("message")
            used.take(message.get("usage") if isinstance(message, dict) else None)
        elif etype == "content_block_start":
            idx = ev.get("index", 0)
            block = ev.get("content_block") or {}
            btype = block.get("type", "text")
            block_index_to_type[idx] = btype
            if btype == "tool_use":
                chat_idx = tc_chat_index
                tc_index_map[idx] = chat_idx
                tc_chat_index += 1
                chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": ts, "model": model_name,
                    "choices": [{"index": 0, "delta": {"tool_calls": [{
                        "index": chat_idx, "id": block.get("id", ""), "type": "function",
                        "function": {"name": block.get("name", ""), "arguments": ""},
                    }]}, "finish_reason": None}],
                }
                yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
        elif etype == "content_block_delta":
            idx = ev.get("index", 0)
            delta = ev.get("delta") or {}
            dtype = delta.get("type", "")
            if dtype == "text_delta":
                chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": ts, "model": model_name,
                    "choices": [{"index": 0, "delta": {"content": delta.get("text", "")}, "finish_reason": None}],
                }
                yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
            elif dtype == "input_json_delta":
                chat_idx = tc_index_map.get(idx, 0)
                chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": ts, "model": model_name,
                    "choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": chat_idx, "function": {"arguments": delta.get("partial_json", "")}}
                    ]}, "finish_reason": None}],
                }
                yield b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
        elif etype == "message_delta":
            delta = ev.get("delta") or {}
            stop_reason = delta.get("stop_reason")
            if stop_reason == "tool_use":
                finish_reason = "tool_calls"
            used.take(ev.get("usage"))
            final = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }
            if used.known():
                final["usage"] = used.openai()
            yield b"data: " + json.dumps(final, separators=(",", ":")).encode() + b"\n\n"
        elif etype == "message_stop":
            break
    yield b"data: [DONE]\n\n"

def _anthropic_to_completions_json(data_bytes, completion_id, model_name):
    """Convert a non-streaming Anthropic Messages response to OpenAI chat.completion format."""
    try:
        resp = json.loads(data_bytes)
    except Exception:
        return data_bytes
    content_blocks = resp.get("content") or []
    text_parts = []
    tool_calls = []
    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {"name": block.get("name", ""),
                             "arguments": json.dumps(block.get("input") or {})},
            })
    finish_reason = "tool_calls" if tool_calls else "stop"
    message = {"role": "assistant", "content": "\n".join(text_parts) or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls
    result = {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": AnthropicUsage().take(resp.get("usage")).openai(),
    }
    return json.dumps(result, ensure_ascii=False).encode("utf-8")

def classify_proxy_error(exc, client_present=False):
    """Name the failure a proxied request died of.

    `client_present` is the one fact this function cannot infer and the caller
    always has. A reset socket means "the client hung up" only when the client
    might have; on the upstream leg, where the handler has already established
    the client is still there, the same errno means the upstream died. Guessing
    it wrong is not cosmetic: the board branches on this value, so a cell that
    accepted a connection and closed it — how a dying llama-server behaves —
    was titled "client disconnected", explained as "client closed connection
    while proxy was still streaming", and left at degraded instead of failed.
    """
    reset = (isinstance(exc, (BrokenPipeError, ConnectionResetError))
             or "Broken pipe" in str(exc) or "Connection reset" in str(exc))
    if reset:
        return "upstream_disconnected" if client_present else "client_disconnected"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "upstream_timeout"
    if "timed out" in str(exc):
        return "upstream_timeout"
    return "proxy_error"
