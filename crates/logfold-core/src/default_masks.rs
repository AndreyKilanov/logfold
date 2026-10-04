//! Hand-written scanner equivalent to the default mask rules of `docs/ALGORITHM.md` §2.
//!
//! It reproduces the one-pass leftmost-first semantics of the combined regular expression (uuid, ts, ip, hex, path,
//! num, in that order, all in ASCII mode) without a regex engine. The differential test in this module compares it with
//! the regex-based masker on random inputs.

const TOKEN_UUID: &[u8] = b"<UUID>";
const TOKEN_TS: &[u8] = b"<TS>";
const TOKEN_IP: &[u8] = b"<IP>";
const TOKEN_HEX: &[u8] = b"<HEX>";
const TOKEN_PATH: &[u8] = b"<PATH>";
const TOKEN_NUM: &[u8] = b"<NUM>";

/// Bytes that can start some rule: digits, hex letters, `/`, `+` and `-`.
const fn candidate_table() -> [bool; 256] {
    let mut table = [false; 256];
    let mut byte = 0usize;
    while byte < 256 {
        let b = byte as u8;
        table[byte] = b.is_ascii_digit() || matches!(b, b'a'..=b'f' | b'A'..=b'F' | b'/' | b'+' | b'-');
        byte += 1;
    }
    table
}

static CANDIDATE: [bool; 256] = candidate_table();

fn is_word(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn word_before(buf: &[u8], at: usize) -> bool {
    at > 0 && is_word(buf[at - 1])
}

fn word_at(buf: &[u8], at: usize) -> bool {
    at < buf.len() && is_word(buf[at])
}

fn digits(buf: &[u8], from: usize) -> usize {
    let mut end = from;
    while end < buf.len() && buf[end].is_ascii_digit() {
        end += 1;
    }
    end
}

fn digits_exact(buf: &[u8], from: usize, count: usize) -> bool {
    from + count <= buf.len() && buf[from..from + count].iter().all(u8::is_ascii_digit)
}

fn hex_exact(buf: &[u8], from: usize, count: usize) -> bool {
    from + count <= buf.len() && buf[from..from + count].iter().all(u8::is_ascii_hexdigit)
}

fn uuid(buf: &[u8], at: usize) -> Option<usize> {
    let groups = [8usize, 4, 4, 4, 12];
    let mut position = at;
    for (index, size) in groups.iter().enumerate() {
        if index > 0 {
            if position >= buf.len() || buf[position] != b'-' {
                return None;
            }
            position += 1;
        }
        if !hex_exact(buf, position, *size) {
            return None;
        }
        position += size;
    }
    Some(position)
}

fn timestamp(buf: &[u8], at: usize) -> Option<usize> {
    if !(digits_exact(buf, at, 4)
        && buf.get(at + 4) == Some(&b'-')
        && digits_exact(buf, at + 5, 2)
        && buf.get(at + 7) == Some(&b'-')
        && digits_exact(buf, at + 8, 2)
        && matches!(buf.get(at + 10), Some(b'T' | b' '))
        && digits_exact(buf, at + 11, 2)
        && buf.get(at + 13) == Some(&b':')
        && digits_exact(buf, at + 14, 2)
        && buf.get(at + 16) == Some(&b':')
        && digits_exact(buf, at + 17, 2))
    {
        return None;
    }
    let mut end = at + 19;
    if matches!(buf.get(end), Some(b'.' | b',')) {
        let after = digits(buf, end + 1);
        if after > end + 1 {
            end = after;
        }
    }
    match buf.get(end) {
        Some(b'Z') => end += 1,
        Some(b'+' | b'-') if digits_exact(buf, end + 1, 2) => {
            if buf.get(end + 3) == Some(&b':') {
                if digits_exact(buf, end + 4, 2) {
                    end += 6;
                }
            } else if digits_exact(buf, end + 3, 2) {
                end += 5;
            }
        }
        _ => {}
    }
    Some(end)
}

fn ip_from(buf: &[u8], octet: usize, at: usize) -> Option<usize> {
    let end_of_digits = digits(buf, at);
    let longest = (end_of_digits - at).min(3);
    for length in (1..=longest).rev() {
        let end = at + length;
        if octet == 3 {
            if let Some(done) = ip_tail(buf, end) {
                return Some(done);
            }
        } else if buf.get(end) == Some(&b'.') {
            if let Some(done) = ip_from(buf, octet + 1, end + 1) {
                return Some(done);
            }
        }
    }
    None
}

fn ip_tail(buf: &[u8], end: usize) -> Option<usize> {
    if buf.get(end) == Some(&b':') {
        let after = digits(buf, end + 1);
        if after > end + 1 && !word_at(buf, after) {
            return Some(after);
        }
    }
    (!word_at(buf, end)).then_some(end)
}

fn ip(buf: &[u8], at: usize) -> Option<usize> {
    if word_before(buf, at) {
        return None;
    }
    ip_from(buf, 0, at)
}

fn hex(buf: &[u8], at: usize) -> Option<usize> {
    if word_before(buf, at) || buf[at] != b'0' || !matches!(buf.get(at + 1), Some(b'x' | b'X')) {
        return None;
    }
    let mut end = at + 2;
    while end < buf.len() && buf[end].is_ascii_hexdigit() {
        end += 1;
    }
    (end > at + 2 && !word_at(buf, end)).then_some(end)
}

fn is_path_char(byte: u8) -> bool {
    is_word(byte) || byte == b'.' || byte == b'-'
}

fn path(buf: &[u8], at: usize) -> Option<usize> {
    let mut end = at;
    let mut segments = 0;
    while buf.get(end) == Some(&b'/') {
        let mut next = end + 1;
        while next < buf.len() && is_path_char(buf[next]) {
            next += 1;
        }
        if next == end + 1 {
            break;
        }
        end = next;
        segments += 1;
    }
    (segments >= 2).then_some(end)
}

fn number(buf: &[u8], at: usize) -> Option<usize> {
    let byte = buf[at];
    let start_digits = if byte == b'+' || byte == b'-' {
        if !word_before(buf, at) {
            return None;
        }
        at + 1
    } else {
        if word_before(buf, at) {
            return None;
        }
        at
    };
    let integer_end = digits(buf, start_digits);
    if integer_end == start_digits {
        return None;
    }
    if buf.get(integer_end) == Some(&b'.') {
        let fraction_end = digits(buf, integer_end + 1);
        if fraction_end > integer_end + 1 && !word_at(buf, fraction_end) {
            return Some(fraction_end);
        }
    }
    (!word_at(buf, integer_end)).then_some(integer_end)
}

fn matched(buf: &[u8], at: usize) -> Option<(usize, &'static [u8])> {
    let byte = buf[at];
    if byte == b'/' {
        return path(buf, at).map(|end| (end, TOKEN_PATH));
    }
    if byte == b'+' || byte == b'-' {
        return number(buf, at).map(|end| (end, TOKEN_NUM));
    }
    if let Some(end) = uuid(buf, at) {
        return Some((end, TOKEN_UUID));
    }
    if byte.is_ascii_digit() {
        if let Some(end) = timestamp(buf, at) {
            return Some((end, TOKEN_TS));
        }
        if let Some(end) = ip(buf, at) {
            return Some((end, TOKEN_IP));
        }
        if let Some(end) = hex(buf, at) {
            return Some((end, TOKEN_HEX));
        }
        return number(buf, at).map(|end| (end, TOKEN_NUM));
    }
    None
}

/// Applies the default rules to `input`. Returns `false` (leaving `out` untouched) when nothing matches.
pub(crate) fn mask_default(input: &[u8], out: &mut Vec<u8>) -> bool {
    let mut cursor = 0;
    let mut position = 0;
    let mut wrote = false;
    while position < input.len() {
        if !CANDIDATE[input[position] as usize] {
            position += 1;
            continue;
        }
        match matched(input, position) {
            Some((end, token)) => {
                if !wrote {
                    out.clear();
                    wrote = true;
                }
                out.extend_from_slice(&input[cursor..position]);
                out.extend_from_slice(token);
                cursor = end;
                position = end;
            }
            None => position += 1,
        }
    }
    if wrote {
        out.extend_from_slice(&input[cursor..]);
    }
    wrote
}
