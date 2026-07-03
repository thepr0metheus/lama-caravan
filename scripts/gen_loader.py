#!/usr/bin/env python3
"""Regenerate the pixel-llama page loader embedded in static/index.html and
static/kanban.html (the block between <div id="appLoader"> and its </div>).

The llamas are 16x13 box-shadow pixel grids drawn DOWNWARD from the anchor —
the ::before carries translateY(-12em) so the hooves sit on the ground line.
Cargo SHAPES define the pixel grids (.pl-s1..sN); body/blanket/cargo COLORS
are CSS custom properties mixed randomly by the inline script — hundreds of
combinations from a few palettes. The hint is localized from the saved UI
language. Run after editing and commit the resulting HTML.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DARK = "#6e5137"
EYE = "#2b2118"
BODY = "var(--pl-body)"
BLANKET = "var(--pl-blanket)"
CARGO = "var(--pl-cargo)"
ROPE = "var(--pl-rope)"


def px(x, y, c):
    return f"{x}em {y}em 0 0 {c}"


def llama(frame, cargo=None):
    """Один кадр одной формы. Цвета — CSS-переменные, их миксует скрипт страницы.
    cargo: None | 'packs' | 'boxes' | 'rug'."""
    P = []
    # уши, голова, глаз, морда
    P += [px(11, 0, BODY), px(13, 0, BODY)]
    for x in range(11, 15):
        P.append(px(x, 1, BODY))
    for x in range(11, 15):
        P.append(px(x, 2, BODY))
    P.append(px(15, 2, DARK))
    P[P.index(px(13, 1, BODY))] = px(13, 1, EYE)
    # шея
    for y in range(3, 6):
        P += [px(10, y, BODY), px(11, y, BODY)]
    # тело
    for y in range(6, 10):
        for x in range(2, 12):
            P.append(px(x, y, BODY))
    # хвост
    P += [px(1, 6, BODY), px(1, 7, BODY)]
    # попона (при «без попоны» скрипт ставит --pl-blanket = --pl-body)
    for y in range(6, 9):
        for x in range(4, 9):
            P[P.index(px(x, y, BODY))] = px(x, y, BLANKET)
    # груз
    if cargo == "boxes":
        for x in range(4, 9):
            for y in (4, 5):
                P.append(px(x, y, CARGO))
        for x in range(5, 8):
            P.append(px(x, 3, ROPE))
        P[P.index(px(5, 4, CARGO))] = px(5, 4, ROPE)
        P[P.index(px(7, 5, CARGO))] = px(7, 5, ROPE)
    elif cargo == "rug":
        for x in range(4, 9):
            P.append(px(x, 5, CARGO))
        P.append(px(3, 5, ROPE))
    elif cargo == "packs":
        for y in range(7, 11):
            P.append(px(3, y, CARGO))
        for y in range(7, 10):
            P.append(px(2, y, CARGO))
        P.append(px(2, 7, ROPE))
    # ноги: 2 кадра походки
    if frame == 0:
        legs = [(3, 10), (3, 11), (3, 12), (10, 10), (10, 11), (10, 12), (5, 10), (5, 11), (8, 10), (8, 11)]
        hooves = [(3, 12), (10, 12)]
    else:
        legs = [(4, 10), (4, 11), (4, 12), (9, 10), (9, 11), (9, 12), (2, 10), (2, 11), (11, 10), (11, 11)]
        hooves = [(4, 12), (9, 12)]
    for x, y in legs:
        entry = px(x, y, BODY)
        if entry not in P:
            P.append(entry)
    for x, y in hooves:
        if px(x, y, BODY) in P:
            P[P.index(px(x, y, BODY))] = px(x, y, DARK)
        elif px(x, y, CARGO) in P:
            pass
        else:
            P.append(px(x, y, DARK))
    return ", ".join(P)


# 4 формы груза × 2 кадра; цвета миксуются переменными → сотни комбинаций
SHAPES = [None, "boxes", "rug", "packs"]

# Пасхалка: зелёная черепашка (см. скрипт страницы — шанс 1/10 занять место ламы).
T_SHELL = "#4d8f5c"
T_PATTERN = "#66ab72"
T_RIM = "#3a6f47"
T_SKIN = "#9cbd72"
T_EYE = "#22301f"


def turtle(frame):
    """Один кадр черепашки: тот же грид, что у лам, ноги на земле (y=12),
    рост втрое ниже ламы. Цвета фиксированные — черепахи зелёные."""
    P = []
    # купол панциря
    for x in range(5, 10):
        P.append(px(x, 7, T_SHELL))
    for x in range(4, 11):
        P.append(px(x, 8, T_SHELL))
    for x in range(3, 12):
        P.append(px(x, 9, T_SHELL))
    # узор
    for x, y in [(6, 8), (8, 8), (5, 9), (7, 9), (9, 9)]:
        P[P.index(px(x, y, T_SHELL))] = px(x, y, T_PATTERN)
    # ободок понизу
    for x in range(3, 12):
        P.append(px(x, 10, T_RIM))
    # хвостик
    P.append(px(2, 10, T_SKIN))
    # голова (глаз спереди сверху)
    P += [px(12, 8, T_SKIN), px(13, 8, T_SKIN), px(12, 9, T_SKIN), px(13, 9, T_SKIN), px(12, 10, T_SKIN)]
    P[P.index(px(13, 8, T_SKIN))] = px(13, 8, T_EYE)
    # лапы: 2 кадра
    legs = [(4, 11), (4, 12), (9, 11), (9, 12)] if frame == 0 else [(5, 11), (5, 12), (10, 11), (10, 12)]
    for x, y in legs:
        P.append(px(x, y, T_SKIN))
    return ", ".join(P)


variant_css = ""
for i, shape in enumerate(SHAPES, 1):
    variant_css += (
        f"      #appLoader .pl-s{i}::before {{ box-shadow: {llama(0, shape)}; }}\n"
        f"      #appLoader .pl-s{i}.pl-gaitb::before {{ box-shadow: {llama(1, shape)}; }}\n"
    )
variant_css += (
    f"      #appLoader .pl-t::before {{ box-shadow: {turtle(0)}; }}\n"
    f"      #appLoader .pl-t.pl-gaitb::before {{ box-shadow: {turtle(1)}; }}\n"
)
# Каждая вторая черепашка передвигается прыжками: подменяем походку на pl-hop
# (шаг ног при этом фиксируем кадром 0 — лапки поджаты в полёте), сохраняя
# фазовые задержки каравана для слотов b/c.
variant_css += (
    "      #appLoader .pl-llama.pl-t-hop { animation: pl-walk 7s linear infinite, pl-hop .6s ease-in-out infinite; }\n"
    "      #appLoader .pl-llama.pl-t-hop.pl-b { animation-delay: -2.4s, 0s; }\n"
    "      #appLoader .pl-llama.pl-t-hop.pl-c { animation-delay: -4.9s, 0s; }\n"
    "      @keyframes pl-hop { 0%, 20%, 100% { margin-bottom: 0; } 55% { margin-bottom: 6px; } }\n"
    f"      #appLoader .pl-llama.pl-t-hop.pl-gaitb::before {{ box-shadow: {turtle(0)}; }}\n"
)

LOADER = f'''  <div id="appLoader" aria-hidden="true">
    <style>
      #appLoader {{ position: fixed; inset: 0; z-index: 9999; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 26px; background: #11171a;
        transition: opacity .35s ease; image-rendering: pixelated; }}
      #appLoader.pl-done {{ opacity: 0; pointer-events: none; }}
      #appLoader .pl-title {{ color: #e7eef1; font: 800 15px/1 -apple-system, "Segoe UI", sans-serif;
        letter-spacing: .42em; text-indent: .42em; opacity: .85; }}
      #appLoader .pl-strip {{ position: relative; width: min(340px, 78vw); height: 84px; overflow: hidden; }}
      #appLoader .pl-strip::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 8px;
        height: 2px; background: rgba(160,180,185,.25); }}
      #appLoader .pl-llama {{ position: absolute; bottom: 10px; left: -110px; width: 1em; height: 1em;
        font-size: 5px; animation: pl-walk 7s linear infinite, pl-gait .45s steps(1, end) infinite; }}
      #appLoader .pl-llama::before {{ content: ""; position: absolute; width: 1em; height: 1em;
        transform: translateY(-12em); }}
      #appLoader .pl-llama.pl-b {{ animation-delay: -2.4s, -.15s; font-size: 4.2px; opacity: .9; }}
      #appLoader .pl-llama.pl-c {{ animation-delay: -4.9s, -.3s; font-size: 3.5px; opacity: .8; }}
      @keyframes pl-walk {{ from {{ transform: translateX(0); }} to {{ transform: translateX(calc(min(340px, 78vw) + 220px)); }} }}
      @keyframes pl-gait {{ 0%, 100% {{ margin-bottom: 0; }} 50% {{ margin-bottom: 1px; }} }}
{variant_css}      #appLoader .pl-hint {{ color: rgba(160,180,185,.6); font: 500 11px/1 -apple-system, "Segoe UI", sans-serif;
        letter-spacing: .18em; }}
    </style>
    <div class="pl-title">LAMA CARAVAN</div>
    <div class="pl-strip">
      <span class="pl-llama"></span>
      <span class="pl-llama pl-b"></span>
      <span class="pl-llama pl-c"></span>
    </div>
    <div class="pl-hint">loading…</div>
    <script>
      (() => {{
        const l = document.getElementById("appLoader");
        // подпись — на языке сохранённого интерфейса (по умолчанию английский)
        const lang = (localStorage.getItem("llamacppAdminLang") || "en").toLowerCase();
        const hints = {{ en: "loading…", ru: "загружается…", zh: "加载中…", es: "cargando…",
          fr: "chargement…", de: "lädt…", ja: "読み込み中…", pt: "carregando…", it: "caricamento…",
          ko: "로딩 중…", tr: "yükleniyor…", vi: "đang tải…" }};
        l.querySelector(".pl-hint").textContent = hints[lang] || hints.en;
        // случайный караван: форма груза × цвет тела × попона × цвет груза —
        // формы задают пиксельную сетку (.pl-s1..s{len(SHAPES)}), цвета миксуются переменными;
        // с шансом 1/10 одно место в караване занимает черепашка
        const BODIES = ["#d9c29a", "#e8e2d4", "#a97e4f", "#b9b3a7", "#8a6f52", "#cbb188"];
        const BLANKETS = ["#43b3a4", "#d98c4a", "#9a7bd0", "#c4574e", "#4f8fd0", "#c9a83b", null];
        const CARGOS = ["#6e5137", "#8a7351", "#5d6657", "#7a4a41"];
        const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
        const walkers = l.querySelectorAll(".pl-llama");
        const turtleAt = Math.random() < 0.1 ? Math.floor(Math.random() * walkers.length) : -1;
        walkers.forEach((el, i) => {{
          if (i === turtleAt) {{
            el.classList.add("pl-t");
            if (Math.random() < 0.5) el.classList.add("pl-t-hop");
            return;
          }}
          el.classList.add("pl-s" + (1 + Math.floor(Math.random() * {len(SHAPES)})));
          const body = pick(BODIES);
          el.style.setProperty("--pl-body", body);
          const blanket = pick(BLANKETS);
          el.style.setProperty("--pl-blanket", blanket || body);
          el.style.setProperty("--pl-cargo", pick(CARGOS));
          el.style.setProperty("--pl-rope", "#c8a06c");
        }});
        // 2-кадровая походка
        const gait = setInterval(() => l && l.querySelectorAll(".pl-llama").forEach(el => el.classList.toggle("pl-gaitb")), 220);
        window.__plHide = () => {{ if (!l || l.classList.contains("pl-done")) return; l.classList.add("pl-done");
          setTimeout(() => {{ clearInterval(gait); l.remove(); }}, 400); }};
        setTimeout(window.__plHide, 20000);  // страховка, если инициализация зависла
      }})();
    </script>
  </div>
'''

BLOCK_RE = re.compile(r'  <div id="appLoader".*?</script>\n  </div>\n', re.S)
for page in ("static/index.html", "static/kanban.html", "static/hf.html"):
    p = ROOT / page
    s = p.read_text(encoding="utf-8")
    if BLOCK_RE.search(s):
        s = BLOCK_RE.sub(LOADER, s, count=1)
    else:
        # первая установка на страницу: сразу после <body>
        assert "<body>\n" in s, f"{page}: <body> not found"
        s = s.replace("<body>\n", "<body>\n" + LOADER, 1)
    p.write_text(s, encoding="utf-8")
    print(f"{page}: loader regenerated ({len(SHAPES)} cargo shapes × color mixes + turtle)")
