//! A reply's head, as bytes.

use crate::headers::Headers;

/// A status line and fields to send.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reply {
    status: u16,
    reason: String,
    headers: Headers,
}

impl Reply {
    /// A reply of `status` under its standard words.
    pub fn new(status: u16) -> Self {
        Self::with_reason(status, Self::standard_reason(status))
    }

    /// A reply of `status` under `reason`: an upstream's own words, relayed.
    pub fn with_reason(status: u16, reason: &str) -> Self {
        Self { status, reason: reason.to_string(), headers: Headers::new() }
    }

    /// Adds a field.
    pub fn field(mut self, name: &str, value: impl Into<Vec<u8>>) -> Self {
        self.headers.push(name, value);
        self
    }

    /// The head's bytes, its blank line included. A value that carries a line end would let an
    /// upstream's words write a field of their own: such a field goes without its line ends.
    pub fn head(&self) -> Vec<u8> {
        let mut out = format!("HTTP/1.1 {} {}\r\n", self.status, Self::single_line(&self.reason)).into_bytes();
        for field in self.headers.iter() {
            out.extend_from_slice(Self::single_line(&field.name).as_bytes());
            out.extend_from_slice(b": ");
            out.extend(field.value.iter().filter(|byte| !matches!(byte, b'\r' | b'\n')));
            out.extend_from_slice(b"\r\n");
        }
        out.extend_from_slice(b"\r\n");
        out
    }

    fn single_line(text: &str) -> String {
        text.chars().filter(|letter| !matches!(letter, '\r' | '\n')).collect()
    }

    /// The words Python's `http.HTTPStatus` gives a status; "" for one it has not.
    pub fn reason_of(status: u16) -> &'static str {
        Self::standard_reason(status)
    }

    fn standard_reason(status: u16) -> &'static str {
        match status {
            200 => "OK",
            201 => "Created",
            202 => "Accepted",
            204 => "No Content",
            206 => "Partial Content",
            301 => "Moved Permanently",
            302 => "Found",
            304 => "Not Modified",
            307 => "Temporary Redirect",
            308 => "Permanent Redirect",
            400 => "Bad Request",
            401 => "Unauthorized",
            402 => "Payment Required",
            403 => "Forbidden",
            404 => "Not Found",
            405 => "Method Not Allowed",
            408 => "Request Timeout",
            409 => "Conflict",
            410 => "Gone",
            413 => "Request Entity Too Large",
            415 => "Unsupported Media Type",
            429 => "Too Many Requests",
            500 => "Internal Server Error",
            501 => "Not Implemented",
            502 => "Bad Gateway",
            503 => "Service Unavailable",
            504 => "Gateway Timeout",
            _ => "",
        }
    }
}

/// A time as a `Date` field says it: `Sun, 06 Nov 1994 08:49:37 GMT`. Takes the time as a parameter:
/// this crate reads no clock.
pub struct HttpDate;

impl HttpDate {
    const DAYS: [&'static str; 7] = ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"];
    const MONTHS: [&'static str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    /// `epoch` seconds as the field's text.
    pub fn format(epoch: u64) -> String {
        let days = epoch / 86_400;
        let second_of_day = epoch % 86_400;
        let (year, month, day) = Self::civil_from_days(days);
        // absent-ok: both indexes are in range by the arithmetic above; clippy asks for no panic, and there is none to name.
        let weekday = Self::DAYS.get((days % 7) as usize).copied().unwrap_or_default();
        // absent-ok: as above.
        let month_name = Self::MONTHS.get((month - 1) as usize).copied().unwrap_or_default();
        format!(
            "{weekday}, {day:02} {month_name} {year} {:02}:{:02}:{:02} GMT",
            second_of_day / 3600,
            second_of_day / 60 % 60,
            second_of_day % 60
        )
    }

    /// `epoch` seconds as `strftime("%Y-%m-%dT%H:%M:%SZ")` writes a moment in UTC: `2026-11-01T15:04:05Z`.
    pub fn iso_z(epoch: i64) -> String {
        let written = Self::iso_utc(epoch);
        format!("{}Z", written.strip_suffix("+00:00").unwrap_or(&written))
    }

    /// `epoch` seconds as `isoformat(timespec="seconds")` writes a moment in UTC: `2026-11-01T15:04:05+00:00`.
    pub fn iso_utc(epoch: i64) -> String {
        // absent-ok: a moment before the epoch is no moment an engine says; it reads as the epoch.
        let epoch = u64::try_from(epoch).unwrap_or_default();
        let (year, month, day) = Self::civil_from_days(epoch / 86_400);
        let second_of_day = epoch % 86_400;
        format!(
            "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}+00:00",
            second_of_day / 3600,
            second_of_day / 60 % 60,
            second_of_day % 60
        )
    }

    /// Days since 1970-01-01 as (year, month, day): Howard Hinnant's `civil_from_days`, for days after the epoch.
    fn civil_from_days(days: u64) -> (u64, u64, u64) {
        let shifted = days + 719_468;
        let era = shifted / 146_097;
        let day_of_era = shifted % 146_097;
        let year_of_era = (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
        let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
        let shifted_month = (5 * day_of_year + 2) / 153;
        let day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
        let month = if shifted_month < 10 { shifted_month + 3 } else { shifted_month - 9 };
        let year = year_of_era + era * 400 + u64::from(month <= 2);
        (year, month, day)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_head_is_a_status_line_and_its_fields() {
        let head = Reply::new(503).field("Content-Length", "2").field("X-Bytes", vec![0xE9]).head();
        assert_eq!(head, b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 2\r\nX-Bytes: \xE9\r\n\r\n");
    }

    #[test]
    fn an_upstream_s_words_cannot_write_a_field_of_their_own() {
        let head = Reply::with_reason(200, "OK\r\nEvil: 1").field("X-Y", "a\r\nEvil: 2").head();
        assert_eq!(head, b"HTTP/1.1 200 OKEvil: 1\r\nX-Y: aEvil: 2\r\n\r\n");
    }

    #[test]
    fn a_status_has_the_words_python_gives_it() {
        for (status, words) in [
            (200, "OK"),
            (201, "Created"),
            (204, "No Content"),
            (400, "Bad Request"),
            (401, "Unauthorized"),
            (402, "Payment Required"),
            (403, "Forbidden"),
            (404, "Not Found"),
            (405, "Method Not Allowed"),
            (408, "Request Timeout"),
            (413, "Request Entity Too Large"),
            (415, "Unsupported Media Type"),
            (429, "Too Many Requests"),
            (500, "Internal Server Error"),
            (501, "Not Implemented"),
            (502, "Bad Gateway"),
            (503, "Service Unavailable"),
            (504, "Gateway Timeout"),
            (299, ""),
        ] {
            assert_eq!(Reply::standard_reason(status), words, "{status}");
        }
    }

    #[test]
    fn dates_read_as_the_rfc_writes_them() {
        assert_eq!(HttpDate::format(784_111_777), "Sun, 06 Nov 1994 08:49:37 GMT");
        assert_eq!(HttpDate::format(0), "Thu, 01 Jan 1970 00:00:00 GMT");
        assert_eq!(HttpDate::format(1_709_164_800), "Thu, 29 Feb 2024 00:00:00 GMT");
        assert_eq!(HttpDate::format(1_793_491_199), "Sat, 31 Oct 2026 23:59:59 GMT");
        // The turns of a leap cycle, as Python's `formatdate` writes them.
        assert_eq!(HttpDate::format(951_825_600), "Tue, 29 Feb 2000 12:00:00 GMT");
        assert_eq!(HttpDate::format(946_684_799), "Fri, 31 Dec 1999 23:59:59 GMT");
        assert_eq!(HttpDate::format(951_868_800), "Wed, 01 Mar 2000 00:00:00 GMT");
        assert_eq!(HttpDate::format(4_107_542_400), "Mon, 01 Mar 2100 00:00:00 GMT");
        assert_eq!(HttpDate::format(4_107_542_399), "Sun, 28 Feb 2100 23:59:59 GMT");
        assert_eq!(HttpDate::format(13_574_563_200), "Tue, 29 Feb 2400 00:00:00 GMT");
        assert_eq!(HttpDate::format(5_097_600), "Sun, 01 Mar 1970 00:00:00 GMT");
        assert_eq!(HttpDate::format(2_147_483_648), "Tue, 19 Jan 2038 03:14:08 GMT");
    }
}
