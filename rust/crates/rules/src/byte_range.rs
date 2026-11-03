//! A `Range` field of a request for a file (RFC 9110): one span of bytes, or the whole file for what asks otherwise.

/// What a `Range` field asks of a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ByteRange {
    /// No span, or one that does not read: the whole file, as the RFC has it.
    Whole,
    /// From this byte to this one, the last included.
    Part {
        /// Its first byte.
        from: u64,
        /// Its last byte.
        to: u64,
    },
    /// A span past the end of the file: 416.
    PastEnd,
}

impl ByteRange {
    /// What `field` asks of a file of `size` bytes.
    pub fn of(field: Option<&str>, size: u64) -> Self {
        let Some(span) = field.and_then(|field| field.trim().strip_prefix("bytes=")) else {
            return Self::Whole;
        };
        let Some((first, last)) = span.split_once('-').filter(|_| !span.contains(',')) else {
            return Self::Whole;
        };
        let (first, last) = (first.trim(), last.trim());
        if first.is_empty() {
            return match last.parse::<u64>() {
                Ok(0) => Self::PastEnd,
                Ok(_) if size == 0 => Self::PastEnd,
                Ok(tail) => Self::Part { from: size.saturating_sub(tail), to: size - 1 },
                Err(_) => Self::Whole,
            };
        }
        let Ok(from) = first.parse::<u64>() else {
            return Self::Whole;
        };
        if from >= size {
            return Self::PastEnd;
        }
        if last.is_empty() {
            return Self::Part { from, to: size - 1 };
        }
        match last.parse::<u64>() {
            Ok(to) if to >= from => Self::Part { from, to: to.min(size - 1) },
            _ => Self::Whole,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ByteRange;

    #[test]
    fn a_span_is_read_as_the_rfc_has_it() {
        let of = |said: &str| ByteRange::of(Some(said), 100);
        assert_eq!(of("bytes=0-0"), ByteRange::Part { from: 0, to: 0 });
        assert_eq!(of("bytes=10-19"), ByteRange::Part { from: 10, to: 19 });
        assert_eq!(of("bytes=90-"), ByteRange::Part { from: 90, to: 99 });
        assert_eq!(of("bytes=90-500"), ByteRange::Part { from: 90, to: 99 }, "past the end is the end");
        assert_eq!(of("bytes=-10"), ByteRange::Part { from: 90, to: 99 });
        assert_eq!(of("bytes=-500"), ByteRange::Part { from: 0, to: 99 });
    }

    #[test]
    fn what_cannot_be_given_is_said_and_what_does_not_read_is_the_whole_file() {
        let of = |said: &str| ByteRange::of(Some(said), 100);
        assert_eq!(of("bytes=100-"), ByteRange::PastEnd);
        assert_eq!(of("bytes=-0"), ByteRange::PastEnd);
        assert_eq!(ByteRange::of(Some("bytes=0-0"), 0), ByteRange::PastEnd, "a file of nothing has no first byte");
        assert_eq!(ByteRange::of(Some("bytes=-5"), 0), ByteRange::PastEnd);
        for said in ["items=0-1", "bytes=a-b", "bytes=5-1", "bytes=0-1,5-6", "bytes=", "nonsense"] {
            assert_eq!(of(said), ByteRange::Whole, "{said}");
        }
        assert_eq!(ByteRange::of(None, 100), ByteRange::Whole);
    }
}
