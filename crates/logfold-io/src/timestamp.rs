//! Timestamp parsing shared by all formats (see `docs/ALGORITHM.md` §1.3).

const MICROS: i64 = 1_000_000;
const MONTHS: [&str; 12] = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
];

/// Parsed result: microseconds since the Unix epoch (UTC) and whether the text carried a zone.
pub type Parsed = (i64, bool);

fn is_leap(year: i64) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_in_month(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ => {
            if is_leap(year) {
                29
            } else {
                28
            }
        }
    }
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let y = year - i64::from(month <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

struct Cursor<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Cursor { bytes, pos: 0 }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn eat(&mut self, byte: u8) -> bool {
        if self.peek() == Some(byte) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn done(&self) -> bool {
        self.pos == self.bytes.len()
    }

    fn digits(&mut self, min: usize, max: usize) -> Option<i64> {
        let mut value: i64 = 0;
        let mut count = 0;
        while count < max {
            match self.peek() {
                Some(b) if b.is_ascii_digit() => {
                    value = value * 10 + i64::from(b - b'0');
                    self.pos += 1;
                    count += 1;
                }
                _ => break,
            }
        }
        (count >= min).then_some(value)
    }

    fn fraction(&mut self) -> Option<i64> {
        let start = self.pos;
        while self.pos - start < 9 && self.peek().is_some_and(|b| b.is_ascii_digit()) {
            self.pos += 1;
        }
        if self.pos == start {
            return None;
        }
        let mut micros: i64 = 0;
        let mut used = 0;
        for &b in &self.bytes[start..self.pos] {
            if used < 6 {
                micros = micros * 10 + i64::from(b - b'0');
                used += 1;
            }
        }
        while used < 6 {
            micros *= 10;
            used += 1;
        }
        Some(micros)
    }

    fn zone(&mut self) -> Option<i64> {
        if self.eat(b'Z') {
            return Some(0);
        }
        let sign = match self.peek() {
            Some(b'+') => 1,
            Some(b'-') => -1,
            _ => return None,
        };
        self.pos += 1;
        let hours = self.digits(2, 2)?;
        let had_colon = self.eat(b':');
        let minutes = match self.digits(2, 2) {
            Some(m) => m,
            None if had_colon => return None,
            None => 0,
        };
        if hours > 23 || minutes > 59 {
            return None;
        }
        Some(sign * (hours * 3600 + minutes * 60))
    }
}

#[derive(Default)]
struct Fields {
    year: Option<i64>,
    month: Option<i64>,
    day: Option<i64>,
    day_of_year: Option<i64>,
    hour: i64,
    minute: i64,
    second: i64,
    micros: i64,
    offset: Option<i64>,
}

impl Fields {
    fn finish(self) -> Option<Parsed> {
        let year = self.year.unwrap_or(1970);
        if self.hour > 23 || self.minute > 59 || self.second > 59 {
            return None;
        }
        let days = if let Some(doy) = self.day_of_year {
            let max = if is_leap(year) { 366 } else { 365 };
            if doy < 1 || doy > max {
                return None;
            }
            days_from_civil(year, 1, 1) + doy - 1
        } else {
            let month = self.month.unwrap_or(1);
            let day = self.day.unwrap_or(1);
            if !(1..=12).contains(&month) || day < 1 || day > days_in_month(year, month) {
                return None;
            }
            days_from_civil(year, month, day)
        };
        let seconds = days * 86_400 + self.hour * 3600 + self.minute * 60 + self.second;
        let micros = seconds.checked_mul(MICROS)?.checked_add(self.micros)?;
        let offset = self.offset.unwrap_or(0);
        Some((micros - offset * MICROS, self.offset.is_some()))
    }
}

/// Parses an ISO-8601 timestamp (`YYYY-MM-DD[(T| )HH:MM[:SS[.f]]][zone]`).
pub fn parse_iso(text: &[u8]) -> Option<Parsed> {
    let mut cur = Cursor::new(text.trim_ascii());
    let mut fields = Fields { year: Some(cur.digits(4, 4)?), ..Fields::default() };
    if !cur.eat(b'-') {
        return None;
    }
    fields.month = Some(cur.digits(2, 2)?);
    if !cur.eat(b'-') {
        return None;
    }
    fields.day = Some(cur.digits(2, 2)?);
    if !cur.done() {
        if !(cur.eat(b'T') || cur.eat(b' ')) {
            return None;
        }
        fields.hour = cur.digits(2, 2)?;
        if !cur.eat(b':') {
            return None;
        }
        fields.minute = cur.digits(2, 2)?;
        if cur.eat(b':') {
            fields.second = cur.digits(2, 2)?;
            if cur.eat(b'.') || cur.eat(b',') {
                fields.micros = cur.fraction()?;
            }
        }
        if !cur.done() {
            fields.offset = Some(cur.zone()?);
        }
    }
    if cur.done() {
        fields.finish()
    } else {
        None
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Item {
    Literal(u8),
    Spaces,
    Year4,
    Year2,
    Month,
    Day,
    DayPadded,
    Hour,
    Minute,
    Second,
    Fraction,
    Zone,
    MonthAbbr,
    MonthFull,
    DayOfYear,
}

/// A compiled `strptime`-style format (`%Y %y %m %d %e %H %M %S %f %z %b %B %j %T %%`).
#[derive(Clone, Debug)]
pub struct TsFormat {
    items: Vec<Item>,
}

impl TsFormat {
    /// Compiles `format`; unknown directives are rejected.
    pub fn new(format: &str) -> Result<Self, String> {
        let bytes = format.as_bytes();
        let mut items = Vec::new();
        let mut index = 0;
        while index < bytes.len() {
            let byte = bytes[index];
            index += 1;
            if byte == b' ' {
                if items.last() != Some(&Item::Spaces) {
                    items.push(Item::Spaces);
                }
            } else if byte != b'%' {
                items.push(Item::Literal(byte));
            } else {
                let directive = *bytes.get(index).ok_or_else(|| "format ends with a lone '%'".to_string())?;
                index += 1;
                match directive {
                    b'Y' => items.push(Item::Year4),
                    b'y' => items.push(Item::Year2),
                    b'm' => items.push(Item::Month),
                    b'd' => items.push(Item::Day),
                    b'e' => items.push(Item::DayPadded),
                    b'H' => items.push(Item::Hour),
                    b'M' => items.push(Item::Minute),
                    b'S' => items.push(Item::Second),
                    b'f' => items.push(Item::Fraction),
                    b'z' => items.push(Item::Zone),
                    b'b' => items.push(Item::MonthAbbr),
                    b'B' => items.push(Item::MonthFull),
                    b'j' => items.push(Item::DayOfYear),
                    b'T' => {
                        items.extend([Item::Hour, Item::Literal(b':'), Item::Minute, Item::Literal(b':'), Item::Second])
                    }
                    b'%' => items.push(Item::Literal(b'%')),
                    other => return Err(format!("unsupported directive '%{}'", other as char)),
                }
            }
        }
        Ok(TsFormat { items })
    }

    /// Parses `text` with this format.
    pub fn parse(&self, text: &[u8]) -> Option<Parsed> {
        let mut cur = Cursor::new(text.trim_ascii());
        let mut fields = Fields::default();
        for item in &self.items {
            match item {
                Item::Literal(byte) => {
                    if !cur.eat(*byte) {
                        return None;
                    }
                }
                Item::Spaces => {
                    if !cur.eat(b' ') {
                        return None;
                    }
                    while cur.eat(b' ') {}
                }
                Item::Year4 => fields.year = Some(cur.digits(4, 4)?),
                Item::Year2 => {
                    let yy = cur.digits(2, 2)?;
                    fields.year = Some(if yy < 69 { 2000 + yy } else { 1900 + yy });
                }
                Item::Month => fields.month = Some(cur.digits(1, 2)?),
                Item::Day => fields.day = Some(cur.digits(1, 2)?),
                Item::DayPadded => {
                    while cur.eat(b' ') {}
                    fields.day = Some(cur.digits(1, 2)?);
                }
                Item::Hour => fields.hour = cur.digits(1, 2)?,
                Item::Minute => fields.minute = cur.digits(1, 2)?,
                Item::Second => fields.second = cur.digits(1, 2)?,
                Item::Fraction => fields.micros = cur.fraction()?,
                Item::Zone => fields.offset = Some(cur.zone()?),
                Item::DayOfYear => fields.day_of_year = Some(cur.digits(1, 3)?),
                Item::MonthAbbr => fields.month = Some(month_name(&mut cur, true)?),
                Item::MonthFull => fields.month = Some(month_name(&mut cur, false)?),
            }
        }
        if cur.done() {
            fields.finish()
        } else {
            None
        }
    }
}

fn month_name(cur: &mut Cursor<'_>, abbreviated: bool) -> Option<i64> {
    let rest = &cur.bytes[cur.pos..];
    for (index, name) in MONTHS.iter().enumerate() {
        let candidate = if abbreviated { &name[..3] } else { name };
        let len = candidate.len();
        if rest.len() >= len && rest[..len].eq_ignore_ascii_case(candidate.as_bytes()) {
            cur.pos += len;
            return Some(index as i64 + 1);
        }
    }
    None
}

/// Converts a JSON integer epoch value (seconds, milliseconds, microseconds or nanoseconds) to microseconds.
pub fn epoch_int_to_micros(value: i64) -> Option<i64> {
    let magnitude = value.unsigned_abs();
    if magnitude < 100_000_000_000 {
        value.checked_mul(MICROS)
    } else if magnitude < 100_000_000_000_000 {
        value.checked_mul(1000)
    } else if magnitude < 100_000_000_000_000_000 {
        Some(value)
    } else {
        Some(value.div_euclid(1000))
    }
}

/// Converts a JSON floating-point epoch value to microseconds.
pub fn epoch_float_to_micros(value: f64) -> Option<i64> {
    if !value.is_finite() {
        return None;
    }
    let magnitude = value.abs();
    let scaled = if magnitude < 1e11 {
        value * 1e6
    } else if magnitude < 1e14 {
        value * 1e3
    } else if magnitude < 1e17 {
        value
    } else {
        value / 1e3
    };
    let rounded = (scaled + 0.5).floor();
    (rounded.abs() < 9.0e18).then_some(rounded as i64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iso_variants() {
        assert_eq!(parse_iso(b"1970-01-01T00:00:01Z"), Some((1_000_000, true)));
        assert_eq!(parse_iso(b"1970-01-01 00:00:01"), Some((1_000_000, false)));
        assert_eq!(parse_iso(b"1970-01-01 03:00:00+03:00"), Some((0, true)));
        assert_eq!(parse_iso(b"2026-10-04T12:00:00.123456789Z"), Some((1_791_115_200_123_456, true)));
        assert_eq!(parse_iso(b"1970-01-02"), Some((86_400_000_000, false)));
        assert_eq!(parse_iso(b"2026-13-01"), None);
        assert_eq!(parse_iso(b"2026-10-04T12:00:00 garbage"), None);
    }

    #[test]
    fn strptime_nginx_and_syslog() {
        let nginx = TsFormat::new("%d/%b/%Y:%H:%M:%S %z").unwrap();
        assert_eq!(nginx.parse(b"04/Oct/2026:12:00:00 +0300"), Some((1_791_104_400_000_000, true)));
        let syslog = TsFormat::new("%b %e %H:%M:%S").unwrap();
        assert_eq!(syslog.parse(b"Jan  2 00:00:01"), Some((86_400_000_000 + 1_000_000, false)));
        assert!(TsFormat::new("%Q").is_err());
    }

    #[test]
    fn epoch_scales() {
        assert_eq!(epoch_int_to_micros(1_700_000_000), Some(1_700_000_000_000_000));
        assert_eq!(epoch_int_to_micros(1_700_000_000_000), Some(1_700_000_000_000_000));
        assert_eq!(epoch_float_to_micros(1.5), Some(1_500_000));
    }
}
