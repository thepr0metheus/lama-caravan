"""Request/response summarization for telemetry events (compact previews,
token usage extraction, stream tail parsing)."""
import json

from caravan.proxy.paths import TEXT_PREVIEW_LIMIT


def compact_text(value):
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    if len(text) > TEXT_PREVIEW_LIMIT:
        return text[:TEXT_PREVIEW_LIMIT].rstrip() + "..."
    return text

def request_summary(body, headers):
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    summary = {
        "contentType": content_type,
        "contentLength": len(body or b""),
    }
    if not body or "json" not in content_type.lower():
        return summary
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        summary["parseError"] = str(exc)
        return summary
    if not isinstance(payload, dict):
        return summary
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    prompt_text_chars = 0
    image_parts = 0
    roles = []
    last_text = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role and role not in roles:
            roles.append(role)
        content = message.get("content")
        if isinstance(content, str):
            prompt_text_chars += len(content)
            last_text = content
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("text", "input_text"):
                    text = str(part.get("text") or "")
                    prompt_text_chars += len(text)
                    last_text = text
                elif "image" in str(part.get("type") or "") or part.get("image_url"):
                    image_parts += 1
    summary.update({
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "maxTokens": payload.get("max_tokens") or payload.get("max_completion_tokens") or payload.get("n_predict"),
        "temperature": payload.get("temperature"),
        "topP": payload.get("top_p"),
        "messages": len(messages),
        "roles": roles,
        "promptTextChars": prompt_text_chars,
        "imageParts": image_parts,
        "tools": len(payload.get("tools") or []) if isinstance(payload.get("tools"), list) else 0,
        "lastTextPreview": compact_text(last_text),
    })
    return {key: value for key, value in summary.items() if value not in (None, "", [])}

def parse_json_bytes(data):
    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {}

def response_summary(payload):
    if not isinstance(payload, dict):
        return {}
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    finish_reasons = [row.get("finish_reason") for row in choices if isinstance(row, dict) and row.get("finish_reason")]
    return {
        "id": payload.get("id"),
        "model": payload.get("model"),
        "object": payload.get("object"),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        # Exact per-request timings from llama.cpp (prompt_n/predicted_n, *_ms,
        # *_per_second, cache_n). The authoritative per-request source.
        "timings": payload.get("timings") if isinstance(payload.get("timings"), dict) else {},
        "choices": len(choices),
        "finishReasons": finish_reasons,
    }

def stream_summary_from_line(line):
    if not line.startswith(b"data:"):
        return {}
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return {"done": data == b"[DONE]"}
    payload = parse_json_bytes(data)
    if not isinstance(payload, dict):
        return {}
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    text_chars = 0
    finish_reasons = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        content = delta.get("content") or choice.get("text") or ""
        text_chars += len(str(content))
        if choice.get("finish_reason"):
            finish_reasons.append(choice.get("finish_reason"))
    return {
        "model": payload.get("model"),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        # llama.cpp puts exact timings in the final streamed chunk (alongside
        # finish_reason) — capture it the same way as usage.
        "timings": payload.get("timings") if isinstance(payload.get("timings"), dict) else {},
        "deltaTextChars": text_chars,
        "finishReasons": finish_reasons,
    }
