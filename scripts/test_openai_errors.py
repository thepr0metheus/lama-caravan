#!/usr/bin/env python3
"""Value snapshot: the entry's language for a consumer — errors, the two dialects, the stream fold.

caravan/proxy/openai_errors.py, caravan/proxy/dialect.py and ChunkFold in
caravan/proxy/translate.py. Pinned: each status gets OpenAI's `type`; a wait
travels as Retry-After, and past an OpenAI client's own patience as
`x-should-retry: false` too; a provider's refusal of the caravan's sign-in is
never a 401 to the consumer; a port's dialect relays everything as it came; a
fold of chat chunks is the chat completion they stream, and says when the
stream ended before its last word.

Run: python3 scripts/test_openai_errors.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from caravan.proxy.dialect import PORT_DIALECT, OpenAIDialect  # noqa: E402
from caravan.proxy.openai_errors import OpenAIError  # noqa: E402
from caravan.proxy.pool_steps import PoolRefusal  # noqa: E402
from caravan.proxy.translate import ChunkFold  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def test_error_shape():
    print("ошибка в форме OpenAI:")
    err = OpenAIError(404, "gone", code="model_not_found", param="model")
    check(json.loads(err.body()) == {"error": {"message": "gone", "type": "invalid_request_error",
                                               "param": "model", "code": "model_not_found"}},
          "тело — error.message, type, param, code")
    for status, kind in ((400, "invalid_request_error"), (401, "invalid_request_error"), (429, "rate_limit_error"),
                         (500, "server_error"), (502, "server_error"), (503, "server_error"), (418, "invalid_request_error")):
        check(OpenAIError(status, "x").type == kind, f"{status} — type {kind}")
    check(OpenAIError(503, "x").headers() == [], "negative: без ожидания — без заголовков")
    check(OpenAIError(429, "x", retry_after=60).headers() == [("Retry-After", "60")],
          "ожидание до минуты — только Retry-After: клиент OpenAI сам подождёт и повторит")
    check(OpenAIError(429, "x", retry_after=61).headers() == [("Retry-After", "61"), ("x-should-retry", "false")],
          "дольше минуты — ещё x-should-retry: false: повторы клиента лимит не переждут")


def test_own_refusals():
    print("отказы входа:")
    check((OpenAIError.no_key().status, OpenAIError.no_key().code) == (401, None)
          and "Authorization: Bearer" in OpenAIError.no_key().message, "нет ключа — 401 и где его ждут")
    wrong = OpenAIError.wrong_key("lcv1_" + "z" * 44 + "abcd")
    check(wrong.status == 401 and wrong.code == "invalid_api_key" and "…abcd." in wrong.message and "zzzz" not in wrong.message,
          "чужой ключ — 401 invalid_api_key, назван четырьмя последними знаками")
    check(OpenAIError.masked("abc") == "…" and OpenAIError.masked(None) == "…", "negative: короткий ключ не показан вовсе")
    check(OpenAIError.shared_key().status == 401, "ключ у двух клиентов — 401, не 409: 409 клиент OpenAI повторяет")
    none = OpenAIError.no_pool()
    check((none.status, none.code, none.param) == (404, "model_not_found", "model") and "connect it to a set of models" in none.message,
          "ключ без каната к набору — 404 model_not_found: модели у ключа нет, и сказано, кто её даёт")
    asked = OpenAIError.no_model()
    check((asked.status, asked.code, asked.param, asked.message) == (400, None, "model", "you must provide a model parameter"),
          "запрос без модели — 400 словами самой OpenAI: модель выбирает пул набора (1.3.497)")
    check(not hasattr(OpenAIError, "missing_model"), "negative: «нет model» больше не отказ — пул ключа служит любому запросу")
    unreadable = OpenAIError.unreadable()
    check(unreadable.status == 400 and "`model`" not in unreadable.message and "multipart/form-data" in unreadable.message
          and "application/json" in unreadable.message,
          "тело ни JSON, ни форма — 400, и сказано, какие два вида вход читает (1.3.501); negative: поля model не требует")
    check(not hasattr(OpenAIError, "not_json"), "negative: «не JSON» больше не отказ сам по себе — вход читает и формы")
    wrong = OpenAIError.unsupported("Standart", "/v1/audio/transcriptions")
    check((wrong.status, wrong.type, wrong.param, wrong.retry_after) == (400, "invalid_request_error", "model", None)
          and wrong.message == "The model `Standart` does not serve POST /v1/audio/transcriptions. Pick a model of your list that does.",
          "модель не делает такой работы — 400 о самом запросе, без Retry-After: ждать нечего, выбрать другую модель")
    check(OpenAIError.unknown_model("X").message == "The model `X` does not exist or you do not have access to it."
          and OpenAIError.unknown_model("X").status == 404, "чужая модель — 404 словами OpenAI")
    check(OpenAIError.invalid_url("POST", "/v1/files").message == "Invalid URL (POST /v1/files)", "путь без ответа — Invalid URL")
    for seconds, words in ((1, "1 s"), (59, "59 s"), (60, "1 min"), (61, "2 min"), (3600, "1 h"), (7380, "2 h 3 min"), (0, "1 s")):
        check(OpenAIError.duration(seconds) == words, f"{seconds} с — «{words}»")


def test_upstream():
    print("отказ провайдера словами каравана:")
    for status in (401, 403):
        err = OpenAIError.upstream(status, "Std", "Incorrect API key provided: sk-…")
        check(err.status == 502 and "sk-" not in err.message and err.code == "upstream_auth",
              f"{status} провайдера — 502: клиент не должен решить, что неверен ЕГО ключ")
    check(OpenAIError.upstream(400, "Std", "too long").message == "too long", "400 — о запросе: слова провайдера идут клиенту")
    check(OpenAIError.upstream(422, "Std", "").message == "The model `Std` refused the request (HTTP 422).",
          "negative: 4xx без слов — свои слова")
    err = OpenAIError.upstream(503, "Std", "at org-x")
    check((err.status, err.code) == (502, "upstream_error") and "org-x" not in err.message, "5xx — 502 без слов провайдера")
    check(OpenAIError.upstream(429, "Std", "org-x limit").retry_after == 30, "429 провайдера — подождать 30 с")
    # The code a local row's cell gave its refusal (1.3.516): told with the words, when it is a word.
    err = OpenAIError.upstream(422, "Arm", "this cell serves another robot", "unsupported_robot_schema")
    check((err.status, err.code, err.type, err.message) == (422, "unsupported_robot_schema", "invalid_request_error",
                                                            "this cell serves another robot"),
          "4xx ячейки: слова и код идут клиенту, код — как у OpenAI (слова через «_»)")
    for odd in (400, 1.5, True, ["a"], {"a": 1}, "", "has space", "org-secret failure at 10.0.0.9", "x" * 65,
                "9starts_with_digit", "кириллица", None):
        check(OpenAIError.upstream(400, "Std", "words", odd).code is None,
              f"negative: «{str(odd)[:20]}» — не код, на который клиент может ветвиться: code остаётся null")
    check(OpenAIError.upstream(400, "Std", "words", "x" * 64).code == "x" * 64
          and OpenAIError.upstream(400, "Std", "words", "a.b-c_9").code == "a.b-c_9",
          "граница: 64 знака и точка, дефис, цифры внутри — код")
    check([OpenAIError.upstream(s, "Std", "words", "cell_said_this").code for s in (401, 403, 429, 500, 503)]
          == ["upstream_auth", "upstream_auth", "rate_limit_exceeded", "upstream_error", "upstream_error"],
          "negative: у 401, 403, 429 и 5xx свои слова и свой код — код ячейки их не заменяет")


def test_dialects():
    print("два способа ответа:")
    status, body, headers = PORT_DIALECT.failure(503, "paused", "blocked")
    check((status, json.loads(body), headers) == (503, {"error": "paused", "kind": "blocked"}, []),
          "порт отвечает, как отвечал всегда")
    check(PORT_DIALECT.answer_error(422, "x", None, code="unsupported_robot_schema") is None,
          "порт код ячейки не трогает: он отвечает, как отвечал всегда")
    check(PORT_DIALECT.header_ok("openai-organization") and PORT_DIALECT.answer_error(500, "x", None) is None
          and PORT_DIALECT.extra_headers("r") == [] and PORT_DIALECT.answers_whole is False,
          "порт передаёт заголовки и ошибки провайдера как пришли, поток остаётся потоком")
    pool = {"id": "std", "name": "Standart"}
    dialect = OpenAIDialect(pool)
    resolved = dialect.resolve({"port": 1, "label": "c", "upstreamType": "llama", "upstreamHost": "127.0.0.1",
                                "upstreamPort": 8080, "queuePlan": {"spec": {}}, "rescueRefs": ["x"]}, {})
    check((resolved["upstreamType"], resolved["providerId"], resolved["routedOutputId"], resolved["routedOutputName"])
          == ("cloud", "std", "cb:std", "Standart") and "queuePlan" not in resolved and "rescueRefs" not in resolved,
          "клиент едет в выход пула — тот же cb:<id>, что у Маршрутизации; хвостов прошлого маршрута нет")
    status, body, headers = dialect.failure(503, "proxy route c is paused", "blocked")
    check(status == 503 and "paused" in json.loads(body)["error"]["message"] and headers == [("Retry-After", "30")],
          "пауза — 503 и подождать")
    status, body, _ = dialect.failure(502, "[Errno 111] Connection refused at 10.0.0.9", "upstream_connect")
    check(status == 502 and b"10.0.0.9" not in body and json.loads(body)["error"]["code"] == "upstream_connect",
          "своя ошибка без адресов и слов изнутри")
    check(dialect.header_ok("Content-Type") and not dialect.header_ok("openai-organization")
          and not dialect.header_ok("X-Agent-Proxy-Chain") and dialect.extra_headers("r1") == [("X-Request-Id", "r1")],
          "клиенту — только свои заголовки и тип; цепочка выходов и заголовки провайдера остаются")
    limit = PoolRefusal({"id": "std", "name": "Standart"}, [{"stepId": "a", "reason": "reserve", "resetAt": 1000 + 7200}], 1000)
    status, body, headers = dialect.answer_error(429, "", limit)
    check(status == 429 and "Standart" in json.loads(body)["error"]["message"] and b'"a"' not in body
          and ("x-should-retry", "false") in headers and ("Retry-After", "7200") in headers,
          "отказ пула — 429 без шагов, с ожиданием до сброса")
    outage = PoolRefusal({"id": "std", "name": "Standart"}, [{"stepId": "a", "reason": "unlisted"}], 1000)
    status, body, _ = dialect.answer_error(503, "", outage)
    check(status == 503 and json.loads(body)["error"]["code"] == "model_unavailable", "пул без подходящего шага не по лимиту — 503")
    status, body, _ = dialect.answer_error(422, "this cell serves another robot", None, code="unsupported_robot_schema")
    error = json.loads(body)["error"]
    check((status, error["code"], error["message"], error["type"]) == (422, "unsupported_robot_schema",
                                                                          "this cell serves another robot", "invalid_request_error"),
          "вход отдаёт отказ ячейки со словами и кодом")
    status, body, _ = dialect.answer_error(422, "words", None)
    check(json.loads(body)["error"]["code"] is None, "negative: код не назван — null, как было")
    # The pool's own refusals keep their words whatever code an upstream passed.
    status, body, _ = dialect.answer_error(503, "", outage, code="cell_said_this")
    check(json.loads(body)["error"]["code"] == "model_unavailable", "negative: отказ самого пула — со своим кодом")


def chunks(*events):
    return [b"data: " + json.dumps(e).encode() + b"\n\n" for e in events] + [b"data: [DONE]\n\n"]


def test_fold():
    print("поток, сложенный в один ответ:")
    fold = ChunkFold()
    for chunk in chunks({"id": "c1", "created": 7, "model": "m", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]},
                        {"id": "c1", "choices": [{"index": 0, "delta": {"content": "Hel"}}]},
                        {"choices": [{"index": 0, "delta": {"content": "lo"}}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}):
        fold.add(chunk)
    check(fold.finished() and fold.completion() == {
        "id": "c1", "object": "chat.completion", "created": 7, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"}, "logprobs": None, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}, "текст собран, причина и расход на месте")
    fold = ChunkFold()
    for chunk in chunks({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 1, "id": "b", "type": "function",
                                                                          "function": {"name": "two", "arguments": ""}}]}}]},
                        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "one"}}]}}]},
                        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"x":'}}]}}]},
                        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}):
        fold.add(chunk)
    message = fold.completion()["choices"][0]["message"]
    check(message == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "one", "arguments": '{"x":1}'}},
        {"id": "b", "type": "function", "function": {"name": "two", "arguments": ""}}]},
          "вызовы по своему индексу, аргументы склеены; без текста content — null, как у OpenAI")
    check("usage" not in fold.completion(), "negative: расхода не было — его и нет")
    cut = ChunkFold()
    for chunk in chunks({"choices": [{"index": 0, "delta": {"content": "Hal"}}]})[:-1]:
        cut.add(chunk)
    check(not cut.finished(), "negative: поток без причины конца — не целый ответ")
    noise = ChunkFold()
    noise.add(b": keepalive\n\ndata: not json\n\ndata: [1, 2]\n\nevent: x\n")
    check(noise.choices == {} and not noise.finished(), "negative: комментарии, не-JSON и не-объекты пропущены")


for fn in (test_error_shape, test_own_refusals, test_upstream, test_dialects, test_fold):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("openai errors snapshot holds")
