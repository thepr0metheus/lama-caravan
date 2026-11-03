//! An ANSI terminal frame as text or HTML, for the monitor panel.

/// One character on the screen.
#[derive(Clone, Default, PartialEq, Eq)]
struct Cell {
    letter: char,
    color: String,
    bold: bool,
}

/// A screen of `rows` by `cols` a frame's bytes are played onto.
struct Screen {
    rows: usize,
    cols: usize,
    cells: Vec<Vec<Cell>>,
    row: usize,
    col: usize,
    color: String,
    bold: bool,
}

impl Screen {
    fn blank() -> Cell {
        Cell { letter: ' ', color: String::new(), bold: false }
    }

    fn new(rows: usize, cols: usize) -> Self {
        Self { rows, cols, cells: vec![vec![Self::blank(); cols]; rows], row: 0, col: 0, color: String::new(), bold: false }
    }

    fn clear(&mut self) {
        self.cells = vec![vec![Self::blank(); self.cols]; self.rows];
        self.row = 0;
        self.col = 0;
    }

    fn style(&mut self, params: &[i64]) {
        if params.is_empty() {
            self.color.clear();
            self.bold = false;
            return;
        }
        let mut at = 0;
        while let Some(param) = params.get(at) {
            match param {
                0 => {
                    self.color.clear();
                    self.bold = false;
                }
                1 => self.bold = true,
                22 => self.bold = false,
                39 => self.color.clear(),
                38 if params.get(at + 1) == Some(&2) => {
                    if let (Some(red), Some(green), Some(blue)) = (params.get(at + 2), params.get(at + 3), params.get(at + 4)) {
                        self.color = format!("rgb({red},{green},{blue})");
                        at += 4;
                    }
                }
                _ => {}
            }
            at += 1;
        }
    }

    fn control(&mut self, code: char, params: &str) {
        let parts: Vec<i64> =
            // absent-ok: a parameter that is no number is 0, as a terminal reads it.
            params.replace('?', "").split(';').filter(|part| !part.is_empty()).map(|part| part.parse().unwrap_or(0)).collect();
        let clamp = |value: Option<&i64>, most: usize| -> usize {
            let one_based = value.copied().filter(|value| *value != 0).unwrap_or(1) - 1;
            // absent-ok: a position before the screen is its first column.
            usize::try_from(one_based.max(0)).unwrap_or(0).min(most.saturating_sub(1))
        };
        match code {
            'H' | 'f' => {
                self.row = clamp(parts.first(), self.rows);
                self.col = clamp(parts.get(1), self.cols);
            }
            'J' => self.clear(),
            'K' => {
                let (row, col) = (self.row, self.col);
                if let Some(line) = self.cells.get_mut(row) {
                    for cell in line.iter_mut().skip(col) {
                        *cell = Self::blank();
                    }
                }
            }
            'm' => self.style(&parts),
            _ => {}
        }
    }

    fn put(&mut self, letter: char) {
        let cell = Cell { letter, color: self.color.clone(), bold: self.bold };
        if let Some(place) = self.cells.get_mut(self.row).and_then(|line| line.get_mut(self.col)) {
            *place = cell;
        }
        self.col += 1;
        if self.col >= self.cols {
            self.col = 0;
            self.row = (self.row + 1).min(self.rows.saturating_sub(1));
        }
    }

    fn play(&mut self, text: &str) {
        let letters: Vec<char> = text.chars().collect();
        let mut at = 0;
        while let Some(letter) = letters.get(at).copied() {
            if letter == '\x1b' {
                match letters.get(at + 1) {
                    Some('[') => {
                        let mut end = at + 2;
                        while letters.get(end).is_some_and(|code| !('@'..='~').contains(code)) {
                            end += 1;
                        }
                        let Some(code) = letters.get(end).copied() else {
                            return;
                        };
                        // absent-ok: no parameters between the bracket and the letter.
                        let params: String = letters.get(at + 2..end).unwrap_or_default().iter().collect();
                        self.control(code, &params);
                        at = end + 1;
                        continue;
                    }
                    Some(']') => {
                        let mut end = at + 2;
                        while letters.get(end).is_some_and(|code| !matches!(code, '\x07' | '\x1b')) {
                            end += 1;
                        }
                        at = letters.len().min(end + 1);
                        continue;
                    }
                    _ => {}
                }
            }
            match letter {
                '\r' => self.col = 0,
                '\n' => {
                    self.row = (self.row + 1).min(self.rows.saturating_sub(1));
                    self.col = 0;
                }
                shown if shown >= ' ' => self.put(shown),
                _ => {}
            }
            at += 1;
        }
    }
}

/// The frames.
pub struct TerminalFrame;

impl TerminalFrame {
    fn escaped(text: &str) -> String {
        text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#39;")
    }

    /// A frame as coloured HTML.
    pub fn to_html(text: &str, rows: usize, cols: usize) -> String {
        let mut screen = Screen::new(rows, cols);
        screen.play(text);
        let mut lines = Vec::with_capacity(rows);
        for line in &screen.cells {
            let end =
                // absent-ok: a line of blanks has nothing to keep.
                line.iter().rposition(|cell| cell.letter != ' ' || !cell.color.is_empty() || cell.bold).map_or(0, |at| at + 1);
            let mut chunks = String::new();
            let (mut held, mut color, mut bold): (String, Option<&str>, Option<bool>) = (String::new(), None, None);
            let flush = |held: &mut String, color: Option<&str>, chunks: &mut String| {
                if held.is_empty() {
                    return;
                }
                let part = Self::escaped(held);
                match color.filter(|color| !color.is_empty()) {
                    Some(color) => chunks.push_str(&format!("<span style=\"color:{color}\">{part}</span>")),
                    None => chunks.push_str(&part),
                }
                held.clear();
            };
            for cell in line.iter().take(end) {
                if Some(cell.color.as_str()) != color || Some(cell.bold) != bold {
                    flush(&mut held, color, &mut chunks);
                    color = Some(cell.color.as_str());
                    bold = Some(cell.bold);
                }
                held.push(cell.letter);
            }
            flush(&mut held, color, &mut chunks);
            lines.push(chunks);
        }
        lines.join("\n").trim_end().to_string()
    }

    /// A frame as plain text.
    pub fn to_text(text: &str, rows: usize, cols: usize) -> String {
        let mut screen = Screen::new(rows, cols);
        screen.play(text);
        let lines: Vec<String> = screen
            .cells
            .iter()
            .map(|line| line.iter().map(|cell| cell.letter).collect::<String>().trim_end().to_string())
            .collect();
        lines.join("\n").trim_end().to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_frame_is_played_as_a_terminal_plays_it() {
        let frame = "\x1b[2J\x1b[1;1Hab\x1b[2;3Hc\x1b[1;2H\x1b[K";
        assert_eq!(TerminalFrame::to_text(frame, 3, 10), "a\n  c");
    }

    #[test]
    fn colour_becomes_a_span_and_markup_is_escaped() {
        let frame = "\x1b[38;2;1;2;3mA<\x1b[0mb";
        assert_eq!(TerminalFrame::to_html(frame, 1, 10), "<span style=\"color:rgb(1,2,3)\">A&lt;</span>b");
    }

    #[test]
    fn a_title_sequence_is_skipped_and_a_long_line_wraps() {
        assert_eq!(TerminalFrame::to_text("\x1b]0;title\x07abc", 2, 2), "ab\nc");
    }
}
