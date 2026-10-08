//! Neutralizing text from a log for the targets of the reports.
//!
//! Each function returns one line of visible characters. Control characters (terminal escape sequences) are shown as
//! `\xNN`, and what the target format treats as markup is made inert on top of that. The `push_*` functions append to
//! a buffer, which is what the reports use on their hot paths; the others return a `String`.

use std::fmt::Write as _;

/// The character that breaks a mention without changing how the text looks.
pub const ZERO_WIDTH_SPACE: char = '\u{200B}';

/// The names after `@` that notify a whole channel.
const GROUP_NAMES: [&str; 4] = ["channel", "here", "everyone", "all"];

/// C0 without tab and line feed, DEL and C1.
fn is_control(c: char) -> bool {
    matches!(c, '\u{0}'..='\u{8}' | '\u{b}'..='\u{1f}' | '\u{7f}'..='\u{9f}')
}

/// Append `text` made one printable line: control characters become `\xNN` and runs of whitespace one space.
pub fn push_flat(out: &mut String, text: &str) {
    let start = out.len();
    let mut gap = false;
    for c in text.chars() {
        let control = is_control(c);
        if !control && c.is_whitespace() {
            gap = true;
            continue;
        }
        if gap && out.len() > start {
            out.push(' ');
        }
        gap = false;
        if control {
            let _ = write!(out, "\\x{:02x}", c as u32);
        } else {
            out.push(c);
        }
    }
}

/// Make text one printable line: control characters become `\xNN` and runs of whitespace one space.
pub fn flatten(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    push_flat(&mut out, text);
    out
}

/// Append `text` made one printable line and cut to `width` characters, with `...` marking the cut.
///
/// With `tail` the end of a long text is kept instead of the start (the file name at the end of a path).
pub fn push_clip(out: &mut String, text: &str, width: usize, tail: bool) {
    let start = out.len();
    push_flat(out, text);
    let flat = &out[start..];
    let count = flat.chars().count();
    if count <= width {
        return;
    }
    let kept = width.saturating_sub(3);
    if tail {
        let cut = flat.char_indices().nth(count - kept).map_or(flat.len(), |(index, _)| index);
        out.replace_range(start..start + cut, "...");
    } else {
        let cut = flat.char_indices().nth(kept).map_or(flat.len(), |(index, _)| index);
        out.truncate(start + cut);
        out.push_str("...");
    }
}

/// Make text one printable line and cut it to `width` characters; see [`push_clip`].
pub fn clip(text: &str, width: usize, tail: bool) -> String {
    let mut out = String::with_capacity(text.len().min(width + 3));
    push_clip(&mut out, text, width, tail);
    out
}

/// Whether `c` is a word character of an ASCII `\b`.
fn is_ascii_word(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

/// Whether `rest` starts with a group name that ends at a word boundary, in any ASCII case.
fn starts_with_group(rest: &[char]) -> bool {
    GROUP_NAMES.iter().any(|name| {
        let length = name.len();
        rest.len() >= length
            && rest.iter().zip(name.chars()).all(|(a, b)| a.eq_ignore_ascii_case(&b))
            && rest.get(length).is_none_or(|next| !is_ascii_word(*next))
    })
}

/// Break the mention syntax of chat systems with a zero-width space, so that a log line cannot ping a channel.
///
/// Slack reads `<!here>`, `<@U123>` and `<#C123>`, Mattermost reads `@channel`, `@here`, `@all` and `@everyone`: a
/// zero-width space goes after `<` before `!`, `@` or `#`, and after `@` before a group name (ASCII case-insensitive,
/// ending at an ASCII word boundary).
pub fn defuse_mentions(text: &str) -> String {
    if !text.contains(['<', '@']) {
        return text.to_owned();
    }
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len() + 4);
    for (index, &c) in chars.iter().enumerate() {
        out.push(c);
        let breaks = match c {
            '<' => chars.get(index + 1).is_some_and(|next| matches!(next, '!' | '@' | '#')),
            '@' => starts_with_group(&chars[index + 1..]),
            _ => false,
        };
        if breaks {
            out.push(ZERO_WIDTH_SPACE);
        }
    }
    out
}

/// Append text as a Markdown code span that cannot be closed from inside (backticks become apostrophes).
pub fn push_code_span(out: &mut String, text: &str, width: usize, tail: bool) {
    out.push('`');
    let start = out.len();
    push_clip(out, text, width, tail);
    if out[start..].contains('`') {
        let fixed = out[start..].replace('`', "'");
        out.truncate(start);
        out.push_str(&fixed);
    }
    out.push('`');
}

/// Return text as a Markdown code span that cannot be closed from inside; see [`push_code_span`].
pub fn code_span(text: &str, width: usize, tail: bool) -> String {
    let mut out = String::new();
    push_code_span(&mut out, text, width, tail);
    out
}

/// Return `before -> after` as two code spans that keep the end of a long path.
pub fn run_names(before: &str, after: &str, width: usize) -> String {
    format!(
        "{} -> {}",
        code_span(&defuse_mentions(before), width, true),
        code_span(&defuse_mentions(after), width, true)
    )
}

/// Append `text` with `&`, `<` and `>` escaped; with `attribute` also `"`.
pub fn push_escaped_xml(out: &mut String, text: &str, attribute: bool) {
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' if attribute => out.push_str("&quot;"),
            _ => out.push(c),
        }
    }
}

/// Escape `&`, `<` and `>`; with `attribute` also `"`.
pub fn escape_xml(text: &str, attribute: bool) -> String {
    let mut out = String::with_capacity(text.len());
    push_escaped_xml(&mut out, text, attribute);
    out
}

/// Return text for an XML 1.0 attribute or element: one line, and U+FFFE and U+FFFF shown as `U+XXXX`.
///
/// Escaping `&`, `<`, `>` and quotes is left to [`escape_xml`].
pub fn xml_text(text: &str, width: usize, tail: bool) -> String {
    let clipped = clip(text, width, tail);
    if !clipped.contains(['\u{FFFE}', '\u{FFFF}']) {
        return clipped;
    }
    let mut out = String::with_capacity(clipped.len() + 8);
    for c in clipped.chars() {
        if matches!(c, '\u{FFFE}' | '\u{FFFF}') {
            let _ = write!(out, "U+{:04X}", c as u32);
        } else {
            out.push(c);
        }
    }
    out
}

/// Append text escaped for a double-quoted Prometheus label value: backslashes and double quotes escaped.
pub fn push_label_value(out: &mut String, text: &str, width: usize) {
    let start = out.len();
    push_clip(out, text, width, false);
    if out[start..].contains(['\\', '"']) {
        let fixed = out[start..].replace('\\', "\\\\").replace('"', "\\\"");
        out.truncate(start);
        out.push_str(&fixed);
    }
}

/// Return text escaped for a double-quoted Prometheus label value; see [`push_label_value`].
pub fn label_value(text: &str, width: usize) -> String {
    let mut out = String::new();
    push_label_value(&mut out, text, width);
    out
}

/// Append an integer with a comma between thousands, as Python's `{:,}`.
pub fn push_group(out: &mut String, number: u64) {
    let mut digits = [0u8; 20];
    let mut length = 0;
    let mut rest = number;
    loop {
        digits[length] = b'0' + (rest % 10) as u8;
        length += 1;
        rest /= 10;
        if rest == 0 {
            break;
        }
    }
    for index in (0..length).rev() {
        out.push(char::from(digits[index]));
        if index > 0 && index.is_multiple_of(3) {
            out.push(',');
        }
    }
}

/// Write an integer with a comma between thousands, as Python's `{:,}`.
pub fn group(number: u64) -> String {
    let mut out = String::new();
    push_group(&mut out, number);
    out
}

/// Return `1 new WARN+ template` or `3 new WARN+ templates`.
pub fn alert_noun(count: u64) -> String {
    format!("{} new WARN+ template{}", group(count), if count == 1 { "" } else { "s" })
}

/// Append `part / total` as a percentage with two decimals, or `-` when there is no total.
pub fn push_share(out: &mut String, part: u64, total: u64) {
    if total == 0 {
        out.push('-');
    } else {
        let _ = write!(out, "{:.2}%", part as f64 / total as f64 * 100.0);
    }
}

/// Format `part / total` as a percentage with two decimals, or `-` when there is no total.
pub fn share(part: u64, total: u64) -> String {
    let mut out = String::new();
    push_share(&mut out, part, total);
    out
}
