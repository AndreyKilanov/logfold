//! A live mining session: records arrive in batches instead of being read from files.
//!
//! A [`Session`] owns the compiled pipeline (format, masks, tokenizer) and one miner. It parses, masks and mines every
//! record exactly as `mine` does for a file, in the order the records are given, so the result equals the one of a
//! sequential run over the same records whatever the size of the batches.

use std::collections::HashMap;
use std::time::Instant;

use logfold_core::{Assignment, DrainMiner, MaskRule, MaskScratch, MatchRule, MinerSnapshot, template_id};
use logfold_io::{Counters, FormatConfig, MAX_LINE_BYTES, MAX_RECORD_BYTES};

use crate::error::EngineError;
use crate::pipeline::PipelineContext;
use crate::types::{MatchBatch, MatchedTemplate, MineOutput, MiningConfig, RunMetrics, RunSummary};
use crate::{empty_miner, load_snapshot, mining_config};

/// Everything needed to open a [`Session`].
#[derive(Clone, Debug)]
pub struct SessionConfig {
    /// Log format of the records.
    pub format: FormatConfig,
    /// Masking rules, applied in order.
    pub masks: Vec<MaskRule>,
    /// Mining parameters.
    pub mining: MiningConfig,
    /// A saved miner to continue from: the new records are mined on top of its tree with empty statistics.
    pub initial: Option<MinerSnapshot>,
}

/// One miner that takes records as they come.
///
/// A session is not thread-safe by itself; share it behind a lock. Records given by several threads are mined in the
/// order in which the lock is taken, so only a single feeder gives a repeatable result.
pub struct Session {
    context: PipelineContext,
    miner: DrainMiner,
    scratch: MaskScratch,
    spans: Vec<(usize, usize)>,
    counters: Counters,
    bytes: u64,
    open: Vec<u8>,
    first_len: usize,
    is_open: bool,
    resumed: bool,
    started: Instant,
}

impl Session {
    /// Compiles the pipeline and builds the miner, empty or from the saved state of `config`.
    ///
    /// # Errors
    /// Fails when the format, a mask or a mining parameter is invalid, or when the saved state was mined with other
    /// parameters or is damaged.
    pub fn new(config: SessionConfig) -> Result<Session, EngineError> {
        let context = PipelineContext::from_parts(&config.format, &config.masks, &config.mining.delimiters)?;
        let miner_config = mining_config(&config.mining)?;
        let loaded = load_snapshot(config.initial.as_ref(), &miner_config, 1)?;
        let resumed = loaded.is_some();
        let mut miner = loaded.unwrap_or_else(|| empty_miner(&miner_config, 1));
        miner.mark_reported();
        Ok(Session {
            context,
            miner,
            scratch: MaskScratch::default(),
            spans: Vec::new(),
            counters: Counters::default(),
            bytes: 0,
            open: Vec::new(),
            first_len: 0,
            is_open: false,
            resumed,
            started: Instant::now(),
        })
    }

    /// Mines complete records, one item per record (an item may hold several lines); returns how many were mined.
    ///
    /// An item is cut at [`MAX_RECORD_BYTES`]. A blank item counts as a line and is skipped; an item that the format
    /// cannot parse counts as unparsed.
    pub fn add_records<'a>(&mut self, records: impl IntoIterator<Item = &'a [u8]>) -> u64 {
        let mut mined = 0;
        for record in records {
            mined += u64::from(self.add_record(record));
        }
        mined
    }

    /// Mines physical lines, joining continuation lines to the record before them as a file would be read; returns how
    /// many records were completed and mined by this call.
    ///
    /// A line may end with `\n` or `\r\n`. A record of a multi-line format stays open until a line that starts the next
    /// record arrives or [`Session::flush`] is called, so the last record of a batch is not yet counted.
    pub fn add_lines<'a>(&mut self, lines: impl IntoIterator<Item = &'a [u8]>) -> u64 {
        let mut mined = 0;
        for raw in lines {
            self.bytes += raw.len() as u64;
            let line = trim_line_end(raw);
            let line = &line[..line.len().min(MAX_LINE_BYTES)];
            mined += u64::from(self.add_line(line));
        }
        mined
    }

    /// Mines the record that is still open, if any; returns how many records were mined (0 or 1).
    pub fn flush(&mut self) -> u64 {
        u64::from(self.close_open())
    }

    /// Texts of the templates created since the previous call (or since the session was opened), in creation order.
    ///
    /// A text is the one the template had when it was created. Templates of a loaded state are not reported.
    pub fn take_new_templates(&mut self) -> Vec<String> {
        self.miner.take_new_texts()
    }

    /// Assigns complete records to the templates that the miner holds, and learns nothing.
    ///
    /// With [`MatchRule::Similar`] the rule is the one of [`crate::match_records`]: the search of training first, then
    /// every template of the same length. With [`MatchRule::Exact`] a record fits a template only when every constant
    /// token of the template equals the token of the record.
    ///
    /// The miner, its counters and the record that is still open are not touched, so the answer for a record does not
    /// depend on the other records of the batch or on how the records are split into calls. A blank item, an item that
    /// the format cannot parse and an item that fits no template are `None`; an item is cut at [`MAX_RECORD_BYTES`].
    pub fn match_records<'a>(&mut self, records: impl IntoIterator<Item = &'a [u8]>, rule: MatchRule) -> MatchBatch {
        let mut batch = MatchBatch::default();
        let mut seen: HashMap<u32, usize> = HashMap::new();
        for record in records {
            let text = &record[..record.len().min(MAX_RECORD_BYTES)];
            let assigned = if is_blank(text) { None } else { self.assign(text, rule, &mut batch, &mut seen) };
            batch.assigned.push(assigned);
        }
        batch
    }

    /// Describes the miner as plain data, the counts of this session folded into the history of the templates.
    pub fn snapshot(&self) -> MinerSnapshot {
        self.miner.snapshot()
    }

    /// Returns the templates and the counters of the records mined so far; the session stays usable.
    ///
    /// A record that is still open is not included until it is completed or flushed. The result costs time and memory in
    /// proportion to the number of templates.
    pub fn output(&self) -> MineOutput {
        let mut templates = self.miner.templates();
        if self.resumed {
            templates.retain(|template| template.total() > 0);
        }
        let run = RunSummary {
            files: 1,
            lines: self.counters.lines,
            records: self.counters.records,
            unparsed: self.counters.unparsed,
            out_of_range: 0,
            untimed: 0,
            bytes: self.bytes,
            tz_aware: self.counters.tz_aware,
            overflowed: self.miner.overflowed().first().copied().unwrap_or(false),
            evicted: self.miner.evicted().first().copied().unwrap_or(0),
        };
        let metrics = RunMetrics {
            strategy: "sequential",
            threads: 1,
            chunks: 0,
            wall_total_s: self.started.elapsed().as_secs_f64(),
            wall_mine_s: 0.0,
            wall_merge_s: 0.0,
            wall_recount_s: 0.0,
            wall_freeze_s: 0.0,
        };
        MineOutput { runs: vec![run], templates, snapshot: None, unmatched: None, check: None, values: None, metrics }
    }

    fn add_record(&mut self, record: &[u8]) -> bool {
        let text = &record[..record.len().min(MAX_RECORD_BYTES)];
        let newlines = text.iter().filter(|&&byte| byte == b'\n').count();
        self.counters.lines += 1 + newlines as u64;
        self.bytes += text.len() as u64;
        if is_blank(text) {
            return false;
        }
        self.mine(text, self.first_line_len(text))
    }

    fn first_line_len(&self, text: &[u8]) -> usize {
        if self.context.format.multiline() {
            text.iter().position(|&byte| byte == b'\n').unwrap_or(text.len())
        } else {
            text.len()
        }
    }

    fn assign(
        &mut self,
        text: &[u8],
        rule: MatchRule,
        batch: &mut MatchBatch,
        seen: &mut HashMap<u32, usize>,
    ) -> Option<usize> {
        let record = self.context.format.parse(text, self.first_line_len(text))?;
        let (tokens, _) = self.context.prepare(&record, &mut self.scratch, &mut self.spans);
        let Assignment::Cluster(cluster) = self.miner.assign_with(&tokens, rule) else {
            return None;
        };
        let miner = &self.miner;
        Some(*seen.entry(cluster).or_insert_with(|| {
            let text = miner.cluster_text(cluster);
            batch.templates.push(MatchedTemplate { id: template_id(&text), text });
            batch.templates.len() - 1
        }))
    }

    fn add_line(&mut self, line: &[u8]) -> bool {
        if !self.context.format.multiline() {
            self.counters.lines += 1;
            return !is_blank(line) && self.mine(line, line.len());
        }
        if !is_blank(line) && self.context.format.starts_record(line) {
            let mined = self.close_open();
            self.counters.lines += 1;
            self.open.clear();
            self.open.extend_from_slice(line);
            self.first_len = line.len();
            self.is_open = true;
            return mined;
        }
        self.counters.lines += 1;
        if !is_blank(line) {
            if !self.is_open {
                self.counters.unparsed += 1;
            } else if self.open.len() < MAX_RECORD_BYTES {
                self.open.push(b'\n');
                self.open.extend_from_slice(line);
            }
        }
        false
    }

    fn close_open(&mut self) -> bool {
        if !self.is_open {
            return false;
        }
        self.is_open = false;
        let record = std::mem::take(&mut self.open);
        let mined = self.mine(&record, self.first_len);
        self.open = record;
        mined
    }

    fn mine(&mut self, text: &[u8], first_len: usize) -> bool {
        let Some(record) = self.context.format.parse(text, first_len) else {
            self.counters.unparsed += 1;
            return false;
        };
        self.counters.records += 1;
        self.counters.tz_aware |= record.tz_aware;
        let (tokens, meta) = self.context.prepare(&record, &mut self.scratch, &mut self.spans);
        self.miner.add(0, &tokens, &meta);
        true
    }
}

fn is_blank(line: &[u8]) -> bool {
    line.iter().all(u8::is_ascii_whitespace)
}

fn trim_line_end(line: &[u8]) -> &[u8] {
    let line = line.strip_suffix(b"\n").unwrap_or(line);
    line.strip_suffix(b"\r").unwrap_or(line)
}
