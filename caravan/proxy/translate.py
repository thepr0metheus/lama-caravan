"""Protocol translation: OpenAI chat-completions <-> Responses API and
Anthropic Messages, both buffered and SSE-streamed, plus proxy error taxonomy."""
import base64 as _b64
import json
import socket
import time


def rewrite_model_in_body(body, model):
    if not body or not model:
        return body
    try:
        payload = json.loads(body)
        if isinstance(payload, dict) and "model" in payload:
            payload["model"] = model
            return json.dumps(payload).encode("utf-8")
    except Exception:
        pass
    return body

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
                        url = (p.get("image_url") or {}).get("url", "")
                        parts.append({"type": "input_image", "detail": "auto", "image_url": url})
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
        "text": {"verbosity": "low"},
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

def _iter_anthropic_as_completions_sse(upstream, completion_id, model_name):
    """Translate Anthropic Messages API SSE stream into chat/completions SSE format."""
    ts = int(time.time())
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
        if etype == "content_block_start":
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
            usage = ev.get("usage") or {}
            final = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }
            if usage.get("output_tokens"):
                final["usage"] = {
                    "prompt_tokens": 0,
                    "completion_tokens": int(usage.get("output_tokens") or 0),
                    "total_tokens": int(usage.get("output_tokens") or 0),
                }
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
    usage = resp.get("usage") or {}
    result = {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": int(usage.get("input_tokens") or 0),
            "completion_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)),
        },
    }
    return json.dumps(result, ensure_ascii=False).encode("utf-8")

def classify_proxy_error(exc):
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return "client_disconnected"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "upstream_timeout"
    text = str(exc)
    if "Broken pipe" in text or "Connection reset" in text:
        return "client_disconnected"
    if "timed out" in text:
        return "upstream_timeout"
    return "proxy_error"
