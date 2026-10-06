use logfold_core::{jaccard_pairs, token_subset_pairs};

const WILDCARD: &str = "<*>";

fn tokens(text: &str) -> Vec<&str> {
    if text.is_empty() { Vec::new() } else { text.split(' ').collect() }
}

fn generalizes(general: &[&str], specific: &[&str]) -> bool {
    general.iter().zip(specific).all(|(g, s)| *g == WILDCARD || g == s)
}

/// Every after template is compared with every unused before template.
fn quadratic_token_subset(before: &[&str], after: &[&str]) -> Vec<(usize, usize)> {
    let before_tokens: Vec<Vec<&str>> = before.iter().map(|t| tokens(t)).collect();
    let mut used = vec![false; before.len()];
    let mut pairs = Vec::new();
    for (j, text) in after.iter().enumerate() {
        let own = tokens(text);
        let mut best: Option<(usize, usize)> = None;
        for (i, candidate) in before_tokens.iter().enumerate() {
            if used[i] || candidate.len() != own.len() {
                continue;
            }
            if generalizes(candidate, &own) || generalizes(&own, candidate) {
                let count = |t: &[&str]| t.iter().filter(|x| **x == WILDCARD).count();
                let key = (count(candidate).abs_diff(count(&own)), i);
                if best.map_or(true, |b| key < b) {
                    best = Some(key);
                }
            }
        }
        if let Some((_, i)) = best {
            used[i] = true;
            pairs.push((i, j));
        }
    }
    pairs
}

fn word_set(text: &str) -> std::collections::BTreeSet<&str> {
    text.split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)).filter(|w| !w.is_empty()).collect()
}

/// Every pair of templates is scored.
fn quadratic_jaccard(before: &[&str], after: &[&str], threshold: f64) -> Vec<(usize, usize)> {
    let (left, right): (Vec<_>, Vec<_>) =
        (before.iter().map(|t| word_set(t)).collect::<Vec<_>>(), after.iter().map(|t| word_set(t)).collect::<Vec<_>>());
    let mut scored = Vec::new();
    for (i, a) in left.iter().enumerate() {
        for (j, b) in right.iter().enumerate() {
            let union = a.union(b).count();
            let score = if union == 0 { 0.0 } else { a.intersection(b).count() as f64 / union as f64 };
            if score >= threshold {
                scored.push((score, i, j));
            }
        }
    }
    scored.sort_by(|x, y| y.0.total_cmp(&x.0).then(x.1.cmp(&y.1)).then(x.2.cmp(&y.2)));
    let (mut used_before, mut used_after) = (vec![false; before.len()], vec![false; after.len()]);
    let mut pairs = Vec::new();
    for (_, i, j) in scored {
        if !used_before[i] && !used_after[j] {
            used_before[i] = true;
            used_after[j] = true;
            pairs.push((i, j));
        }
    }
    pairs.sort_unstable();
    pairs
}

fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *state >> 33
}

fn random_templates(state: &mut u64, count: usize) -> Vec<String> {
    const WORDS: [&str; 9] = ["a", "b", "c", "d", "<*>", "<*>", "", "é", "user"];
    (0..count)
        .map(|_| {
            let length = next(state) % 7;
            (0..length).map(|_| WORDS[(next(state) % WORDS.len() as u64) as usize]).collect::<Vec<_>>().join(" ")
        })
        .collect()
}

#[test]
fn token_subset_prefers_fewer_wildcard_differences_then_the_lowest_index() {
    let before = ["user <*> failed", "user <*> <*>", "user bob failed", "user bob failed"];
    assert_eq!(token_subset_pairs(&before, &["user bob failed"]), vec![(2, 0)]);
    assert_eq!(token_subset_pairs(&["a <*>", "a <*>"], &["a b"]), vec![(0, 0)]);
    assert_eq!(token_subset_pairs(&["", ""], &["", ""]), vec![(0, 0), (1, 1)]);
    assert!(token_subset_pairs(&[], &["a"]).is_empty());
    assert!(token_subset_pairs(&["a"], &[]).is_empty());
}

#[test]
fn jaccard_takes_the_best_pairs_first() {
    let before = ["disk full on sda", "user alice failed login", "unrelated words only"];
    let after = ["user bob failed login", "disk full on sdb", "something else entirely"];
    assert_eq!(jaccard_pairs(&before, &after, 0.5), vec![(0, 1), (1, 0)]);
    assert!(jaccard_pairs(&before, &after, 1.0).is_empty());
    assert!(jaccard_pairs(&["", " "], &["", ""], 0.5).is_empty());
}

#[test]
fn indexed_search_equals_the_quadratic_search() {
    let mut state = 17;
    for round in 0..300 {
        let (before, after) =
            (random_templates(&mut state, 1 + round % 40), random_templates(&mut state, 1 + round % 37));
        let (b, a): (Vec<&str>, Vec<&str>) =
            (before.iter().map(String::as_str).collect(), after.iter().map(String::as_str).collect());
        assert_eq!(token_subset_pairs(&b, &a), quadratic_token_subset(&b, &a), "round {round}");
        for threshold in [0.0, 0.2, 0.5, 0.6, 2.0 / 3.0, 0.9, 1.0, 1.5] {
            assert_eq!(
                jaccard_pairs(&b, &a, threshold),
                quadratic_jaccard(&b, &a, threshold),
                "round {round}, {threshold}"
            );
        }
    }
}

#[test]
fn unicode_separators_split_words_like_python() {
    let before = ["a\u{1c}b\u{a0}c\u{2003}d"];
    let after = ["a b c d"];
    assert_eq!(jaccard_pairs(&before, &after, 1.0), vec![(0, 0)]);
}

mod classification {
    use logfold_core::{Changed, Matcher, Side, Thresholds, compare_runs};

    const DEFAULT: Thresholds = Thresholds { ratio: 2.0, min_count: 10, min_new_count: 1 };

    fn side<'a>(texts: &'a [&'a str], counts: &'a [u64], total: u64) -> Side<'a> {
        Side { texts, counts, total }
    }

    #[test]
    fn splits_new_disappeared_changed_and_unchanged() {
        let before = side(&["steady", "grew", "shrank", "gone", "tiny"], &[100, 10, 100, 5, 3], 1000);
        let after = side(&["steady", "grew", "shrank", "brand new", "tiny"], &[200, 100, 10, 7, 9], 2000);
        let result = compare_runs(&before, &after, &DEFAULT, Matcher::Exact);
        assert_eq!(result.new, vec![3]);
        assert_eq!(result.disappeared, vec![3]);
        let changed: Vec<(usize, f64)> = result.changed.iter().map(|c| (c.after, c.ratio.unwrap())).collect();
        assert_eq!(changed, vec![(2, (10.0 / 2000.0) / (100.0 / 1000.0)), (1, (100.0 / 2000.0) / (10.0 / 1000.0))]);
        assert_eq!(result.unchanged, 2);
    }

    #[test]
    fn thresholds_decide_what_is_reported() {
        let texts = ["a", "b", "c"];
        let before = side(&texts, &[10, 1, 0], 100);
        let after = side(&texts, &[30, 5, 1], 100);
        let reported = |thresholds: Thresholds| -> (usize, usize) {
            let result = compare_runs(&before, &after, &thresholds, Matcher::Exact);
            (result.changed.len(), result.new.len())
        };
        assert_eq!(reported(Thresholds { ratio: 4.0, min_count: 2, min_new_count: 1 }), (1, 1));
        assert_eq!(reported(Thresholds { ratio: 2.0, min_count: 6, min_new_count: 1 }), (1, 1));
        assert_eq!(reported(Thresholds { ratio: 10.0, min_count: 0, min_new_count: 2 }), (0, 0));
    }

    #[test]
    fn a_matcher_pairs_one_sided_templates_and_the_second_run_gives_the_text() {
        let before = side(&["user alice failed", "unrelated"], &[40, 5], 100);
        let after = side(&["user <*> failed"], &[45], 100);
        let exact = compare_runs(&before, &after, &DEFAULT, Matcher::Exact);
        assert_eq!((exact.new.len(), exact.disappeared.len()), (1, 2));
        let merged = compare_runs(&before, &after, &DEFAULT, Matcher::TokenSubset);
        assert_eq!((merged.new.len(), merged.disappeared.len(), merged.unchanged), (0, 1, 1));
        let jaccard = compare_runs(&before, &after, &DEFAULT, Matcher::Jaccard(0.5));
        assert_eq!((jaccard.new.len(), jaccard.disappeared.len()), (0, 1));
    }

    #[test]
    fn zero_counts_are_not_part_of_the_run_and_zero_totals_give_zero_shares() {
        let texts = ["a", "b"];
        let before = side(&texts, &[0, 20], 100);
        let after = side(&texts, &[5, 0], 100);
        let result = compare_runs(&before, &after, &DEFAULT, Matcher::Exact);
        assert_eq!((result.new, result.disappeared), (vec![0], vec![1]));
        let empty = side(&texts, &[20, 20], 0);
        let result =
            compare_runs(&empty, &empty, &Thresholds { ratio: 1.0, min_count: 0, min_new_count: 0 }, Matcher::Exact);
        assert_eq!(result.changed.len(), 2);
        for entry in &result.changed {
            assert_eq!((entry.before_share, entry.after_share, entry.ratio), (0.0, 0.0, None));
        }
        let reversed = compare_runs(&side(&texts, &[20, 20], 100), &empty, &DEFAULT, Matcher::Exact);
        assert_eq!(reversed.changed, Vec::<Changed>::new());
        assert_eq!(reversed.unchanged, 2);
    }

    #[test]
    fn lists_are_sorted_by_significance_then_text() {
        let before = side(&["x", "y", "z"], &[10, 10, 10], 100);
        let after = side(&["x", "y", "z", "p", "q"], &[40, 40, 20, 3, 3], 100);
        let result =
            compare_runs(&before, &after, &Thresholds { ratio: 1.5, min_count: 0, min_new_count: 1 }, Matcher::Exact);
        assert_eq!(result.changed.iter().map(|c| c.after).collect::<Vec<_>>(), vec![0, 1, 2]);
        assert_eq!(result.new, vec![3, 4]);
    }
}
