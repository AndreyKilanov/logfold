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
    let window = ScanWindow {
        skip_first_line: mid_file,
        skip_leading_continuations: mid_file && context.format.multiline(),
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
