#![allow(missing_docs)]

use logfold_report::text::{
    ZERO_WIDTH_SPACE, alert_noun, clip, code_span, defuse_mentions, escape_xml, flatten, group, label_value, share,
    xml_text,
};
use logfold_report::{Analysis, Diff, Row, Run, Subject, chat_message, github_summary, is_alert, junit, prometheus};

fn zws(text: &str) -> String {
    text.replace('|', &ZERO_WIDTH_SPACE.to_string())
}

#[test]
fn flatten_shows_controls_and_collapses_whitespace() {
    assert_eq!(flatten("  a \t\n b\u{a0}\u{2028}c  "), "a b c");
    assert_eq!(flatten("x\u{1b}[31my\u{7f}\u{85}"), "x\\x1b[31my\\x7f\\x85");
    assert_eq!(flatten("a\u{b}b\u{1c}c"), "a\\x0bb\\x1cc");
    assert_eq!(flatten(""), "");
    assert_eq!(flatten(" \t "), "");
}

#[test]
fn clip_cuts_by_characters_and_keeps_the_head_or_the_tail() {
    assert_eq!(clip("abcdef", 6, false), "abcdef");
    assert_eq!(clip("abcdefg", 6, false), "abc...");
    assert_eq!(clip("abcdefg", 6, true), "...efg");
    assert_eq!(clip("日本語のテキスト", 6, false), "日本語...");
    assert_eq!(clip("日本語のテキスト", 6, true), "...キスト");
    assert_eq!(clip("a \n b", 10, false), "a b");
}

#[test]
fn mentions_are_broken_after_their_first_character() {
    assert_eq!(defuse_mentions("<!here> <@U1> <#C1>"), zws("<|!here> <|@U1> <|#C1>"));
    assert_eq!(defuse_mentions("@channel @HERE @all @everyone"), zws("@|channel @|HERE @|all @|everyone"));
    assert_eq!(defuse_mentions("@all. @all, @all"), zws("@|all. @|all, @|all"));
}

#[test]
fn text_that_only_looks_like_a_mention_is_left_alone() {
    for text in ["@channels", "@all_", "@allé", "@here1", "user@example.com", "<NUM>", "<*>", "a < b", "<", "@"] {
        let expected = if text == "@allé" { zws("@|allé") } else { text.to_owned() };
        assert_eq!(defuse_mentions(text), expected, "{text}");
    }
}

#[test]
fn code_spans_cannot_be_closed_from_inside() {
    assert_eq!(code_span("a `rm -rf` b", 100, false), "`a 'rm -rf' b`");
    assert_eq!(code_span("x", 100, false), "`x`");
}

#[test]
fn xml_text_shows_the_two_non_characters_and_escaping_is_separate() {
    assert_eq!(xml_text("a\u{fffe}b\u{ffff}c", 100, false), "aU+FFFEbU+FFFFc");
    assert_eq!(escape_xml("a&b<c>d\"e", false), "a&amp;b&lt;c&gt;d\"e");
    assert_eq!(escape_xml("a&b<c>d\"e", true), "a&amp;b&lt;c&gt;d&quot;e");
}

#[test]
fn label_values_escape_backslashes_and_quotes() {
    assert_eq!(label_value("a\\b\"c", 100), "a\\\\b\\\"c");
    assert_eq!(label_value("a\nb", 100), "a b");
}

#[test]
fn numbers_are_written_as_python_does() {
    assert_eq!(group(0), "0");
    assert_eq!(group(999), "999");
    assert_eq!(group(1000), "1,000");
    assert_eq!(group(1_234_567), "1,234,567");
    assert_eq!(group(u64::MAX), "18,446,744,073,709,551,615");
    assert_eq!(share(1, 3), "33.33%");
    assert_eq!(share(1, 8), "12.50%");
    assert_eq!(share(0, 0), "-");
    assert_eq!(share(1, 0), "-");
    assert_eq!(alert_noun(1), "1 new WARN+ template");
    assert_eq!(alert_noun(1200), "1,200 new WARN+ templates");
}

fn row<'a>(text: &'a str, level: Option<&'a str>, before: u64, after: u64) -> Row<'a> {
    Row { id: "0123456789abcdef", text, level, before, after, ..Row::default() }
}

fn run(name: &str, records: u64) -> Run<'_> {
    Run { name, records, unparsed: 0 }
}

#[test]
fn only_warn_and_above_are_alerts() {
    for level in ["WARN", "ERROR", "FATAL"] {
        assert!(is_alert(Some(level)));
    }
    for level in [None, Some("INFO"), Some("DEBUG"), Some("warn"), Some("")] {
        assert!(!is_alert(level));
    }
}

fn fixture() -> (Vec<Row<'static>>, Vec<Row<'static>>, Vec<Row<'static>>) {
    let new = vec![
        row("quiet new", Some("INFO"), 0, 50),
        row("db down <!here> `x`", Some("ERROR"), 0, 7),
        row("no level", None, 0, 3),
        row("disk full", Some("WARN"), 0, 2),
    ];
    let changed = vec![Row { ratio: Some(3.0), ..row("slow", Some("INFO"), 10, 30) }];
    let gone = vec![row("old", None, 4, 0)];
    (new, changed, gone)
}

fn diff<'a>(new: &'a [Row<'a>], changed: &'a [Row<'a>], gone: &'a [Row<'a>], warnings: &'a [&'a str]) -> Diff<'a> {
    Diff {
        before: run("before.log", 1000),
        after: run("after.log", 1200),
        new,
        changed,
        disappeared: gone,
        unchanged: 9,
        warnings,
    }
}

#[test]
fn github_summary_lists_alerts_first_and_collapses_the_rest() {
    let (new, changed, gone) = fixture();
    let text = github_summary(&Subject::Diff(diff(&new, &changed, &gone, &[])), 20, 1_000_000);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(lines[0], "## logfold: `before.log` -> `after.log`");
    assert_eq!(lines[2], "**2 new WARN+ templates.**");
    assert_eq!(lines[6], "| 4 | 2 | 1 | 1 | 9 | 1,000 -> 1,200 |");
    let items: Vec<&&str> = lines.iter().filter(|line| line.starts_with("- ")).collect();
    assert_eq!(items[0], &"- **ERROR** 7 `db down <!here> 'x'`");
    assert_eq!(items[1], &"- **WARN** 2 `disk full`");
    assert!(text.contains("<details><summary>Changed templates (1)</summary>"));
    assert!(text.contains("- **INFO** x3.00 (10 -> 30) `slow`"));
    assert!(text.contains("- 4 -> 0 `old`"));
    assert!(text.ends_with("</details>\n"));
}

#[test]
fn github_summary_is_cut_to_the_byte_budget() {
    let (new, changed, gone) = fixture();
    let subject = Subject::Diff(diff(&new, &changed, &gone, &[]));
    let full = github_summary(&subject, 20, 1_000_000);
    let cut = github_summary(&subject, 20, full.len() - 1);
    assert!(cut.len() < full.len());
    assert!(cut.contains("_Lists are shortened to"));
    assert!(!full.contains("_Lists are shortened to"));
    let none = github_summary(&subject, 20, 1);
    assert!(none.contains("### New templates (0 of 4)"));
}

#[test]
fn github_summary_of_an_analysis_shows_the_share_and_the_levels() {
    let templates = [row("hot", Some("ERROR"), 0, 3), row("cold", None, 0, 1)];
    let levels = [("INFO", 1), ("ERROR", 3)];
    let analysis = Analysis { run: run("a.log", 4), templates: &templates, levels: &levels, warnings: &["careful"] };
    let text = github_summary(&Subject::Analysis(analysis), 1, 1_000_000);
    assert!(text.contains("4 records, 2 templates, 0 unparsed lines."));
    assert!(text.contains("Levels: ERROR 3, INFO 1"));
    assert!(text.contains("> warning: `careful`"));
    assert!(text.contains("### Most frequent templates (1 of 2)"));
    assert!(text.contains("- **ERROR** 3 (75.00%) `hot`"));
    assert!(!text.contains("cold"));
}

#[test]
fn junit_fails_the_alerts_and_passes_the_rest() {
    let (new, changed, gone) = fixture();
    let text = junit(&diff(&new, &changed, &gone, &[]), 1);
    assert!(text.starts_with("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites>\n"));
    assert!(text.contains("tests=\"3\" failures=\"2\""));
    assert_eq!(text.matches("<failure ").count(), 2);
    assert_eq!(text.matches("<testcase ").count(), 3);
    assert!(text.contains("classname=\"logfold.new.ERROR\" name=\"db down &lt;!here&gt; `x` [01234567]\""));
    assert!(text.contains("message=\"new ERROR template, 7 records\" type=\"ERROR\""));
    assert!(text.contains("records: 7 (0.58% of the run)"));
    assert!(text.contains("<property name=\"unchanged_templates\" value=\"9\" />"));
    assert!(text.ends_with("</testsuite>\n</testsuites>\n"));
}

#[test]
fn junit_with_nothing_new_has_one_passing_case() {
    let text = junit(&diff(&[], &[], &[], &[]), 100);
    assert!(text.contains("tests=\"1\" failures=\"0\""));
    assert!(text.contains("<testcase classname=\"logfold.new\" name=\"no new templates\" time=\"0\" />"));
}

#[test]
fn chat_message_drops_templates_instead_of_cutting_them() {
    let (new, changed, gone) = fixture();
    let subject = Subject::Diff(diff(&new, &changed, &gone, &[]));
    let text = chat_message(&subject, 5, 3000);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(lines[1], "2 new WARN+ templates of 4 new, 1 disappeared, 1 changed.");
    assert_eq!(lines[2], "New templates:");
    assert!(lines[3].starts_with("- ERROR 7 x `db down <"));
    assert!(!text.contains("<!here>"));
    let short = chat_message(&subject, 5, 150);
    assert!(short.lines().last().unwrap().starts_with("... and "));
    assert!(chat_message(&subject, 0, 3000).ends_with("... and 4 more\n"));
}

#[test]
fn prometheus_writes_one_family_at_a_time_and_bounds_the_series() {
    let (new, changed, gone) = fixture();
    let text = prometheus(&Subject::Diff(diff(&new, &changed, &gone, &[])), 1);
    assert!(text.contains("# TYPE logfold_diff_records gauge\nlogfold_diff_records{side=\"before\"} 1000\n"));
    assert!(text.contains("logfold_diff_new_alerts 2\n"));
    let series = text.lines().filter(|line| line.starts_with("logfold_diff_template_records{")).count();
    assert_eq!(series, 3 * 2);
    assert!(
        text.contains(
            "change=\"new\",id=\"0123456789abcdef\",level=\"INFO\",template=\"quiet new\",side=\"after\"} 50"
        )
    );
    assert!(text.ends_with('\n'));
}
