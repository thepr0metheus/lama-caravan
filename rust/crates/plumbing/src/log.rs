//! A program's own words, on its standard error: what the journal of its machine keeps.

/// The one place a program prints.
pub struct Log;

impl Log {
    /// Says `words`.
    pub fn line(words: &str) {
        #[allow(clippy::print_stderr, reason = "this is the one place a program prints")]
        {
            eprintln!("{words}");
        }
    }
}

impl Log {
    /// Says `words` on the standard output: what a child process answers its parent with.
    pub fn out(words: &str) {
        #[allow(clippy::print_stdout, reason = "this is the one place a program prints its answer")]
        {
            println!("{words}");
        }
    }
}

/// A number as `f"{n:,}"` writes it.
pub struct Thousands;

impl Thousands {
    /// `1234567` as `1,234,567`.
    pub fn of(number: i64) -> String {
        let digits = number.unsigned_abs().to_string();
        let mut out = String::with_capacity(digits.len() + digits.len() / 3 + 1);
        if number < 0 {
            out.push('-');
        }
        for (at, digit) in digits.chars().enumerate() {
            if at != 0 && (digits.len() - at).is_multiple_of(3) {
                out.push(',');
            }
            out.push(digit);
        }
        out
    }
}
