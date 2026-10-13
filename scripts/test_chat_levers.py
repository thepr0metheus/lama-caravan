#!/usr/bin/env python3
"""Value snapshot: OpenAI's reasoning_effort, verbosity and image detail, said to the row that
serves — caravan/common/chat_levers.py and the subscription's translator (1.3.501).

The defects. A subscription's row lost all three: the translator sent no reasoning effort, fixed
the verbosity at "low" and every image's detail at "auto" — sinapse steers them and would have lost
them through the caravan. A llama.cpp cell was never told "no thinking": gemma-4 through the entry
spent a short answer's every token on thinking and answered nothing (2026-10-12).

Pinned. The subscription's Responses body takes the client's effort as `reasoning.effort` (none
asked — no `reasoning`), its verbosity as `text.verbosity` (none or a word it does not know — "low",
as before), each image's detail from its `image_url` ("auto" when unsaid). A cell's chat request
with effort "none" or "minimal" gets `chat_template_kwargs.enable_thinking: false`, its other
template words kept; anything else — another effort, the client's own enable_thinking, a body that
is not JSON, a path that is not a chat's — goes as the same bytes.

Run: python3 scripts/test_chat_levers.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caravan.common.chat_levers import ChatLevers  # noqa: E402
from caravan.proxy.translate import _chat_to_responses_body  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def responses(**chat):
    body = {"model": "gpt-sol", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "what is here?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}}]}], **chat}
    out, _model = _chat_to_responses_body(json.dumps(body).encode(), "gpt-6.1-sol")
    return json.loads(out)


def section_subscription():
    print("подписке — рычаги клиента словами Responses API:")
    sent = responses(reasoning_effort="high", verbosity="medium")
    check(sent.get("reasoning") == {"effort": "high"} and sent.get("text") == {"verbosity": "medium"},
          f"reasoning_effort → reasoning.effort, verbosity → text.verbosity (got {sent.get('reasoning')} {sent.get('text')})")
    images = [p for p in sent["input"][0]["content"] if p["type"] == "input_image"]
    check([p["detail"] for p in images] == ["high", "auto"], f"detail картинки — как у клиента, не сказано — auto (got {images})")
    plain = responses()
    check("reasoning" not in plain and plain.get("text") == {"verbosity": "low"},
          "negative: клиент ничего не просил — reasoning нет, verbosity low, как было всегда")
    odd = responses(verbosity="loud", reasoning_effort="   ")
    check("reasoning" not in odd and odd["text"] == {"verbosity": "low"}, "negative: слово не из стандарта — тихое low; пустое усилие — не просьба")
    check(responses(reasoning_effort="xhigh")["reasoning"] == {"effort": "xhigh"},
          "усилие передаётся как написано: судит провайдер, а не караван")


def section_cell():
    print("ячейке llama.cpp — «не думай» словами её шаблона:")
    chat = "/v1/chat/completions"
    for effort in ("none", "minimal"):
        body = json.dumps({"model": "gemma", "messages": [], "reasoning_effort": effort}).encode()
        out = json.loads(ChatLevers.for_cell(body, chat))
        check(out["chat_template_kwargs"] == {"enable_thinking": False} and out["reasoning_effort"] == effort,
              f"reasoning_effort {effort} → chat_template_kwargs.enable_thinking false")
    kept = json.dumps({"messages": [], "reasoning_effort": "none", "chat_template_kwargs": {"preserve": True}}).encode()
    check(json.loads(ChatLevers.for_cell(kept, chat + "?x=1"))["chat_template_kwargs"] == {"preserve": True, "enable_thinking": False},
          "другие слова шаблона клиента сохранены; путь с вопросом — тот же путь")
    unchanged = [
        *((json.dumps({"messages": [], "reasoning_effort": effort}).encode(), chat, f"усилие {effort}: думать можно")
          for effort in ("low", "medium", "high")),
        (json.dumps({"messages": []}).encode(), chat, "усилия нет"),
        (json.dumps({"reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": True}}).encode(), chat,
         "клиент сам сказал enable_thinking — его слово сильнее"),
        (b"--b\r\nform", chat, "тело не JSON"),
        (json.dumps({"input": "x", "reasoning_effort": "none"}).encode(), "/v1/embeddings", "путь не чата"),
        (b"", chat, "пустое тело"),
    ]
    for body, path, why in unchanged:
        check(ChatLevers.for_cell(body, path) is body, f"negative: {why} — те же байты, тот же объект")


def main():
    for fn in (section_subscription, section_cell):
        fn()
    if _fail:
        print(f"\nchat levers FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nchat levers OK: подписке — reasoning, text и detail клиента; ячейке — «не думай» её шаблоном")
    return 0


if __name__ == "__main__":
    sys.exit(main())
