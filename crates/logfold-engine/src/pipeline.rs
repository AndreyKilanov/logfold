use logfold_core::{DrainMiner, MaskRule, MaskScratch, RecordMeta, Recount, RuleMasker, TokenView, Tokenizer};
use logfold_io::{
    CompiledFormat, Counters, FormatConfig, IoError, LineReader, ParsedRecord, ScanOutcome, ScanWindow, open_source,
    scan_records,
};

use crate::error::EngineError;
use crate::plan::WorkUnit;
use crate::types::{MineRequest, ProgressObserver};
use crate::valuing::{ValuePlan, record_with_values};

/// Compiled, immutable parts of the pipeline shared by all workers.
pub(crate) struct PipelineContext {
    pub(crate) format: CompiledFormat,
    pub(crate) masker: RuleMasker,
    pub(crate) tokenizer: Tokenizer,
}

impl PipelineContext {
    pub(crate) fn new(request: &MineRequest) -> Result<Self, EngineError> {
        Self::from_parts(&request.format, &request.masks, &request.mining.delimiters)
    }

    pub(crate) fn from_parts(
        format: &FormatConfig,
        masks: &[MaskRule],
        delimiters: &[u8],
    ) -> Result<Self, EngineError> {
        Ok(PipelineContext {
            format: CompiledFormat::new(format)?,
            masker: RuleMasker::new(masks)?,
            tokenizer: Tokenizer::new(delimiters)?,
        })
    }

    /// Masks and tokenizes the message of `record` into the reusable buffers `scratch` and `spans`.
    pub(crate) fn prepare<'a>(
        &self,
        record: &'a ParsedRecord<'_>,
        scratch: &'a mut MaskScratch,
        spans: &'a mut Vec<(usize, usize)>,
    ) -> (TokenView<'a>, RecordMeta<'a>) {
        let masked = self.masker.mask(&record.message, scratch);
        self.tokenizer.tokenize(masked, spans);
        let tokens = TokenView::new(masked, spans);
        let meta = RecordMeta { message: &record.message, timestamp: record.timestamp, level: record.level };
        (tokens, meta)
    }
}

struct Feeder<'c> {
    context: &'c PipelineContext,
    scratch: MaskScratch,
    spans: Vec<(usize, usize)>,
}

impl Feeder<'_> {
    fn prepare<'a>(&'a mut self, record: &'a ParsedRecord<'_>) -> (TokenView<'a>, RecordMeta<'a>) {
        self.context.prepare(record, &mut self.scratch, &mut self.spans)
    }
}

/// How far back a unit looks for the entry that comes before it.
const LOOKBACK_BYTES: u64 = 64 << 10;

/// For a format that joins entries: true when the last entry before `unit.start` has no line break at its end, so the
/// first lines of the unit are the end of a record that the previous unit finishes.
///
/// An entry that is longer than [`LOOKBACK_BYTES`], or that cannot be read, counts as one that ends its line.
fn continues_previous_entry(context: &PipelineContext, unit: &WorkUnit) -> Result<bool, IoError> {
    if !context.format.joins_entries() {
        return Ok(false);
    }
    let from = unit.start.saturating_sub(LOOKBACK_BYTES);
    let source = open_source(&unit.path, &unit.info, from)?;
    let mut reader = LineReader::new(source, from);
    let mut skip = from > 0;
    let mut continues = false;
    while let Some(line) = reader.next_line().map_err(|source| IoError::Read { path: unit.path.clone(), source })? {
        if line.start >= unit.start {
            break;
        }
        if skip {
            skip = false;
        } else if !line.bytes.iter().all(u8::is_ascii_whitespace) {
            continues = context.format.parse_entry(line.bytes).is_some_and(|entry| !entry.terminated);
        }
    }
    Ok(continues)
}

/// Scans one unit and hands every record, masked and tokenized, to `on_record` together with its run.
pub(crate) fn scan_unit<F>(
    context: &PipelineContext,
    unit: &WorkUnit,
    observer: &dyn ProgressObserver,
    mut on_record: F,
) -> Result<Counters, EngineError>
where
    F: FnMut(usize, &TokenView<'_>, &RecordMeta<'_>),
{
    let begin = unit.start.saturating_sub(1);
    let source = open_source(&unit.path, &unit.info, begin)?;
    let reader = LineReader::new(source, begin);
    let mid_file = unit.start > 0;
    let continues = mid_file && (context.format.multiline() || continues_previous_entry(context, unit)?);
    let window = ScanWindow {
        skip_first_line: mid_file,
        skip_leading_continuations: continues,
        end: unit.end,
        time: unit.window,
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
    context: &PipelineContext,
    unit: &WorkUnit,
    miner: &mut DrainMiner,
    observer: &dyn ProgressObserver,
) -> Result<Counters, EngineError> {
    scan_unit(context, unit, observer, |run, tokens, meta| miner.add(run, tokens, meta))
}

/// Assigns the records of one unit to the clusters of the finished `miner`.
pub(crate) fn recount_unit(
    context: &PipelineContext,
    unit: &WorkUnit,
    miner: &DrainMiner,
    recount: &mut Recount,
    values: Option<&ValuePlan>,
    observer: &dyn ProgressObserver,
) -> Result<Counters, EngineError> {
    scan_unit(context, unit, observer, |run, tokens, meta| {
        record_with_values(context, miner, recount, values, run, tokens, meta);
    })
}
