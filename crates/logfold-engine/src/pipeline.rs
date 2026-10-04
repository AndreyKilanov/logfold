use logfold_core::{DrainMiner, MaskScratch, RecordMeta, Recount, RuleMasker, TokenView, Tokenizer};
use logfold_io::{
    open_source, scan_records, CompiledFormat, Counters, IoError, LineReader, ParsedRecord, ScanOutcome, ScanWindow,
};

use crate::error::EngineError;
use crate::plan::Unit;
use crate::request::{MineRequest, Observer};

/// Compiled, immutable parts of the pipeline shared by all workers.
pub(crate) struct Context {
    pub(crate) format: CompiledFormat,
    pub(crate) masker: RuleMasker,
    pub(crate) tokenizer: Tokenizer,
}

impl Context {
    pub(crate) fn new(request: &MineRequest) -> Result<Self, EngineError> {
        Ok(Context {
            format: CompiledFormat::new(&request.format)?,
            masker: RuleMasker::new(&request.masks)?,
            tokenizer: Tokenizer::new(&request.mining.delimiters)?,
        })
    }
}

struct Feeder<'c> {
    context: &'c Context,
    scratch: MaskScratch,
    spans: Vec<(usize, usize)>,
}

impl Feeder<'_> {
    fn prepare<'a>(&'a mut self, record: &'a ParsedRecord<'_>) -> (TokenView<'a>, RecordMeta<'a>) {
        let masked = self.context.masker.mask(&record.message, &mut self.scratch);
        self.context.tokenizer.tokenize(masked, &mut self.spans);
        let tokens = TokenView::new(masked, &self.spans);
        let meta = RecordMeta { message: &record.message, timestamp: record.timestamp, level: record.level };
        (tokens, meta)
    }
}

/// Scans one unit and hands every record, masked and tokenized, to `on_record` together with its run.
pub(crate) fn scan_unit<F>(
    context: &Context,
    unit: &Unit,
    observer: &dyn Observer,
    mut on_record: F,
) -> Result<Counters, EngineError>
where
    F: FnMut(usize, &TokenView<'_>, &RecordMeta<'_>),
{
    let begin = unit.start.saturating_sub(1);
    let source = open_source(&unit.path, &unit.info, begin)?;
    let reader = LineReader::new(source, begin);
    let mid_file = unit.start > 0;
    let window = ScanWindow {
        skip_first_line: mid_file,
        skip_leading_continuations: mid_file && context.format.multiline(),
        end: unit.end,
    };
    let mut feeder = Feeder { context, scratch: MaskScratch::default(), spans: Vec::new() };
    let run = unit.run;
    let (counters, outcome) = scan_records(
        reader,
        &context.format,
        window,
        |record| {
            let (tokens, meta) = feeder.prepare(record);
            on_record(run, &tokens, &meta);
        },
        |consumed| {
            observer.on_bytes(consumed);
            !observer.cancelled()
        },
    )
    .map_err(|source| IoError::Read { path: unit.path.clone(), source })?;
    match outcome {
        ScanOutcome::Finished => Ok(counters),
        ScanOutcome::Stopped => Err(EngineError::Cancelled),
    }
}

/// Trains `miner` on one unit and returns its counters.
pub(crate) fn train_unit(
    context: &Context,
    unit: &Unit,
    miner: &mut DrainMiner,
    observer: &dyn Observer,
) -> Result<Counters, EngineError> {
    scan_unit(context, unit, observer, |run, tokens, meta| miner.add(run, tokens, meta))
}

/// Assigns the records of one unit to the clusters of the finished `miner`.
pub(crate) fn recount_unit(
    context: &Context,
    unit: &Unit,
    miner: &DrainMiner,
    recount: &mut Recount,
    observer: &dyn Observer,
) -> Result<Counters, EngineError> {
    scan_unit(context, unit, observer, |run, tokens, meta| recount.record(miner, run, tokens, meta))
}
