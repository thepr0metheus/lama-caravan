"""ANSI terminal frame rendering (btop snapshots) for the monitor panel."""
import re


def terminal_frame_to_html(text, rows=40, cols=120):
    screen = [[{"ch": " ", "fg": "", "bold": False} for _ in range(cols)] for _ in range(rows)]
    row = 0
    col = 0
    fg = ""
    bold = False
    i = 0

    def clear_screen():
        for y in range(rows):
            for x in range(cols):
                screen[y][x] = {"ch": " ", "fg": "", "bold": False}

    def apply_sgr(params):
        nonlocal fg, bold
        if not params:
            fg = ""
            bold = False
            return
        j = 0
        while j < len(params):
            p = params[j]
            if p == 0:
                fg = ""
                bold = False
            elif p == 1:
                bold = True
            elif p == 22:
                bold = False
            elif p == 39:
                fg = ""
            elif p == 38 and j + 4 < len(params) and params[j + 1] == 2:
                r, g, b = params[j + 2], params[j + 3], params[j + 4]
                fg = f"rgb({r},{g},{b})"
                j += 4
            j += 1

    while i < len(text):
        ch = text[i]
        if ch == "\x1b":
            if i + 1 < len(text) and text[i + 1] == "[":
                j = i + 2
                while j < len(text) and not ("@" <= text[j] <= "~"):
                    j += 1
                if j >= len(text):
                    break
                params = text[i + 2:j]
                code = text[j]
                clean = params.replace("?", "")
                parts = [int(p) if p.isdigit() else 0 for p in clean.split(";") if p != ""]
                if code in ("H", "f"):
                    row = max(0, min(rows - 1, (parts[0] if len(parts) > 0 and parts[0] else 1) - 1))
                    col = max(0, min(cols - 1, (parts[1] if len(parts) > 1 and parts[1] else 1) - 1))
                elif code == "J":
                    clear_screen()
                    row = 0
                    col = 0
                elif code == "K":
                    for x in range(col, cols):
                        screen[row][x] = {"ch": " ", "fg": "", "bold": False}
                elif code == "m":
                    apply_sgr(parts)
                i = j + 1
                continue
            if i + 1 < len(text) and text[i + 1] == "]":
                j = i + 2
                while j < len(text) and text[j] not in ("\a", "\x1b"):
                    j += 1
                i = min(len(text), j + 1)
                continue
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row = min(rows - 1, row + 1)
            col = 0
        elif ch >= " ":
            if 0 <= row < rows and 0 <= col < cols:
                screen[row][col] = {"ch": ch, "fg": fg, "bold": bold}
            col += 1
            if col >= cols:
                col = 0
                row = min(rows - 1, row + 1)
        i += 1

    def esc(value):
        return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace('"', "&quot;").replace("'", "&#39;"))

    lines = []
    for line in screen:
        while line and line[-1]["ch"] == " " and not line[-1]["fg"] and not line[-1]["bold"]:
            line = line[:-1]
        chunks = []
        cur_fg = None
        cur_bold = None
        buf = []

        def flush():
            nonlocal buf
            if not buf:
                return
            text_part = esc("".join(buf))
            style = []
            if cur_fg:
                style.append(f"color:{cur_fg}")
            if style:
                chunks.append(f'<span style="{";".join(style)}">{text_part}</span>')
            else:
                chunks.append(text_part)
            buf = []

        for cell in line:
            cell_fg = cell["fg"]
            cell_bold = cell["bold"]
            if cell_fg != cur_fg or cell_bold != cur_bold:
                flush()
                cur_fg = cell_fg
                cur_bold = cell_bold
            buf.append(cell["ch"])
        flush()
        lines.append("".join(chunks))
    return "\n".join(lines).rstrip()

def terminal_frame_to_text(text, rows=40, cols=120):
    screen = [[" " for _ in range(cols)] for _ in range(rows)]
    row = 0
    col = 0
    i = 0

    def clear_screen():
        for y in range(rows):
            for x in range(cols):
                screen[y][x] = " "

    while i < len(text):
        ch = text[i]
        if ch == "\x1b":
            if i + 1 < len(text) and text[i + 1] == "[":
                j = i + 2
                while j < len(text) and not ("@" <= text[j] <= "~"):
                    j += 1
                if j >= len(text):
                    break
                params = text[i + 2:j]
                code = text[j]
                clean = params.replace("?", "")
                parts = [int(p) if p.isdigit() else 0 for p in clean.split(";") if p != ""]
                if code in ("H", "f"):
                    row = max(0, min(rows - 1, (parts[0] if len(parts) > 0 and parts[0] else 1) - 1))
                    col = max(0, min(cols - 1, (parts[1] if len(parts) > 1 and parts[1] else 1) - 1))
                elif code == "J":
                    clear_screen()
                    row = 0
                    col = 0
                elif code == "K":
                    for x in range(col, cols):
                        screen[row][x] = " "
                i = j + 1
                continue
            if i + 1 < len(text) and text[i + 1] == "]":
                j = i + 2
                while j < len(text) and text[j] not in ("\a", "\x1b"):
                    j += 1
                i = min(len(text), j + 1)
                continue
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row = min(rows - 1, row + 1)
            col = 0
        elif ch >= " ":
            if 0 <= row < rows and 0 <= col < cols:
                screen[row][col] = ch
            col += 1
            if col >= cols:
                col = 0
                row = min(rows - 1, row + 1)
        i += 1

    return "\n".join("".join(line).rstrip() for line in screen).rstrip()
