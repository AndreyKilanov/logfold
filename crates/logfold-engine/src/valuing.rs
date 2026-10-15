//! The values of the most frequent templates, collected in the pass that assigns records to the finished tree: their
//! distributions (ADR-016) or, for two runs, which values are new and which are gone (ADR-018).

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;

use logfold_core::{
    Assignment, Change, Distribution, DrainMiner, Fit, MAX_PER_CHUNK, MAX_PER_RUN, RecordMeta, Recount, Slot,
    TokenView, ValueCollector, ValueSet, WILDCARD_NAME, Wanted, compare_values, default_mask_rules, extract_parameters,
    template_id,
};

use crate::error::EngineError;
use crate::pipeline::PipelineContext;
use crate::types::{PositionChange, PositionValues, TemplateChanges, TemplateValues, ValuesRequest};

/// What the pass that assigns records collects.
#[derive(Clone)]
enum Collect {
    /// The distributions of the values (ADR-016).
    Distributions,
    /// The sets of values, to tell the new from the gone ones (ADR-018).
    Presence,
    /// The text of the values that the sets named as new or gone.
    Texts(Arc<Wanted>),
}

/// The templates whose values are collected, with their tokens.
pub(crate) struct ValuePlan {
    templates: HashMap<u32, Vec<Box<[u8]>>>,
    /// The names of the rules whose values are collected: the default rules. A value that a mask set of the user hides
    /// (a key, an e-mail address) is never counted, so a report cannot show it.
    names: Vec<String>,
    collect: Collect,
}

impl ValuePlan {
    /// Picks the `request.templates` most frequent clusters of `miner`.
    pub(crate) fn new(miner: &DrainMiner, request: ValuesRequest) -> Self {
        let templates = miner
            .top_clusters(request.templates)
            .into_iter()
            .map(|index| (index, miner.cluster_tokens(index).to_vec()))
            .collect();
        let collect = if request.compare { Collect::Presence } else { Collect::Distributions };
        ValuePlan { templates, names: default_mask_rules().into_iter().map(|rule| rule.name).collect(), collect }
    }

    /// Whether the plan compares two runs.
    pub(crate) fn compares(&self) -> bool {
        !matches!(self.collect, Collect::Distributions)
    }

    /// The same templates, collecting the text of `wanted`.
    fn texts(&self, wanted: Wanted) -> Self {
        ValuePlan {
            templates: self.templates.clone(),
            names: self.names.clone(),
            collect: Collect::Texts(Arc::new(wanted)),
        }
    }

    /// The collector of one run; a chunk in work (`partial`) keeps fewer values than the total of a run.
    fn collector(&self, partial: bool) -> ValueCollector {
        match &self.collect {
            Collect::Distributions => ValueCollector::default(),
            Collect::Presence => ValueCollector::presence(if partial { MAX_PER_CHUNK } else { MAX_PER_RUN }),
            Collect::Texts(wanted) => ValueCollector::texts(Arc::clone(wanted)),
        }
    }

    /// Counts the values of `record`, which `recount` has just assigned to `assignment`.
    pub(crate) fn collect(
        &self,
        context: &PipelineContext,
        recount: &mut Recount,
        run: usize,
        assignment: Assignment,
        record: &RecordMeta<'_>,
    ) {
        let Assignment::Cluster(index) = assignment else { return };
        let Some(tokens) = self.templates.get(&index) else { return };
        if let Some(mut parameters) =
            extract_parameters(&context.masker, &context.tokenizer, tokens, record.message, Fit::ByPosition)
        {
            parameters.retain(|parameter| parameter.name == WILDCARD_NAME || self.names.contains(&parameter.name));
            recount.add_values(run, index, &parameters);
        }
    }
}

/// A recount for `n_runs` runs that also collects the values when there is a plan; `partial` for the part of one chunk.
pub(crate) fn new_recount(
    n_runs: usize,
    rule: logfold_core::MatchRule,
    plan: Option<&ValuePlan>,
    partial: bool,
) -> Recount {
    let recount = Recount::with_rule(n_runs, rule);
    match plan {
        Some(plan) => recount.with_collector(plan.collector(partial)),
        None => recount,
    }
}

/// Assigns the record to the finished tree and, for a template that is tracked, counts its values.
pub(crate) fn record_with_values(
    context: &PipelineContext,
    miner: &DrainMiner,
    recount: &mut Recount,
    plan: Option<&ValuePlan>,
    run: usize,
    tokens: &TokenView<'_>,
    record: &RecordMeta<'_>,
) {
    let assignment = recount.record(miner, run, tokens, record);
    if let Some(plan) = plan {
        plan.collect(context, recount, run, assignment, record);
    }
}

/// Turns the collectors of the runs into the values of the templates, by the text of the template: the clusters with the
/// same text are summed in the order of their indexes.
pub(crate) fn summarize(miner: &DrainMiner, collectors: Vec<ValueCollector>) -> Vec<TemplateValues> {
    let n_runs = collectors.len();
    let mut by_text: BTreeMap<String, Vec<BTreeMap<Slot, Distribution>>> = BTreeMap::new();
    for (run, collector) in collectors.into_iter().enumerate() {
        for (cluster, slots) in collector.into_clusters() {
            let runs = by_text.entry(miner.cluster_text(cluster)).or_insert_with(|| vec![BTreeMap::new(); n_runs]);
            for (slot, distribution) in slots {
                match runs[run].get_mut(&slot) {
                    Some(existing) => existing.merge(&distribution),
                    None => {
                        runs[run].insert(slot, distribution);
                    }
                }
            }
        }
    }
    by_text
        .into_iter()
        .map(|(text, runs)| TemplateValues {
            id: template_id(&text),
            text,
            runs: runs
                .into_iter()
                .map(|slots| {
                    slots
                        .into_iter()
                        .map(|((position, name), distribution)| PositionValues {
                            position,
                            name,
                            summary: distribution.summary(),
                        })
                        .collect()
                })
                .collect(),
        })
        .collect()
}

/// The sets of the two runs of a template, with the clusters that have its text.
#[derive(Default)]
struct Group {
    clusters: Vec<u32>,
    runs: [BTreeMap<Slot, ValueSet>; 2],
    present: [bool; 2],
}

/// The template, the clusters with its text and the positions whose values differ.
type Found = (String, Vec<u32>, Vec<(Slot, Change)>);

/// A value whose text the second pass did not find (the log changed between the passes) is shown by its fingerprint.
fn shown(text: Option<&Vec<u8>>, key: u64) -> Vec<u8> {
    text.map_or_else(|| format!("#{key:016x}").into_bytes(), Clone::clone)
}

/// Groups the sets of the two runs by the text of the template.
fn group_by_text(miner: &DrainMiner, collectors: [ValueCollector; 2]) -> BTreeMap<String, Group> {
    let mut groups: BTreeMap<String, Group> = BTreeMap::new();
    for (run, collector) in collectors.into_iter().enumerate() {
        let Some(presence) = collector.into_presence() else { continue };
        for (cluster, slots) in presence.into_clusters() {
            let group = groups.entry(miner.cluster_text(cluster)).or_default();
            if !group.clusters.contains(&cluster) {
                group.clusters.push(cluster);
            }
            group.present[run] = true;
            for (slot, set) in slots {
                group.runs[run].entry(slot).or_default().merge(&set);
            }
        }
    }
    groups
}

/// Compares the two runs of every template that both have; fills `wanted` with the values to show.
fn differences(groups: BTreeMap<String, Group>, wanted: &mut Wanted) -> Vec<Found> {
    let empty = ValueSet::default();
    let mut found = Vec::new();
    for (text, group) in groups {
        if !(group.present[0] && group.present[1]) {
            continue;
        }
        let slots: BTreeSet<&Slot> = group.runs[0].keys().chain(group.runs[1].keys()).collect();
        let mut changes = Vec::new();
        for slot in slots {
            let before = group.runs[0].get(slot).unwrap_or(&empty);
            let after = group.runs[1].get(slot).unwrap_or(&empty);
            let Some(change) = compare_values(before, after) else { continue };
            let keys: Vec<u64> = change.new.iter().chain(&change.gone).map(|&(key, _)| key).collect();
            if !keys.is_empty() {
                for &cluster in &group.clusters {
                    wanted.entry(cluster).or_default().push((slot.clone(), keys.clone()));
                }
            }
            changes.push((slot.clone(), change));
        }
        if !changes.is_empty() {
            found.push((text, group.clusters, changes));
        }
    }
    for slots in wanted.values_mut() {
        slots.sort_by(|a, b| a.0.cmp(&b.0));
    }
    found
}

/// Turns the sets of the two runs into the values that are new and gone, by the text of the template. The text of the
/// values comes from `rescan`, a pass that collects the text of the fingerprints it is given.
pub(crate) fn value_changes(
    miner: &DrainMiner,
    plan: &ValuePlan,
    collectors: Vec<ValueCollector>,
    rescan: &dyn Fn(&ValuePlan) -> Result<Vec<ValueCollector>, EngineError>,
) -> Result<Vec<TemplateChanges>, EngineError> {
    let pair: [ValueCollector; 2] =
        collectors.try_into().map_err(|_| EngineError::Config("comparing the values needs exactly two runs".into()))?;
    let mut wanted = Wanted::new();
    let found = differences(group_by_text(miner, pair), &mut wanted);
    let mut texts: HashMap<(u32, Slot), BTreeMap<u64, Vec<u8>>> = HashMap::new();
    if !wanted.is_empty() {
        for collector in rescan(&plan.texts(wanted))? {
            let Some(collected) = collector.into_texts() else { continue };
            for (cluster, slots) in collected.into_found() {
                for (slot, values) in slots {
                    texts.entry((cluster, slot)).or_default().extend(values);
                }
            }
        }
    }
    Ok(found
        .into_iter()
        .map(|(text, clusters, changes)| {
            let positions = changes
                .into_iter()
                .map(|(slot, change)| {
                    let list = |entries: &[(u64, u64)]| {
                        let mut values: Vec<(Vec<u8>, u64)> = entries
                            .iter()
                            .map(|&(key, count)| {
                                let known =
                                    clusters.iter().find_map(|&cluster| texts.get(&(cluster, slot.clone()))?.get(&key));
                                (shown(known, key), count)
                            })
                            .collect();
                        values.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
                        values
                    };
                    PositionChange {
                        position: slot.0,
                        name: slot.1.clone(),
                        new: list(&change.new),
                        gone: list(&change.gone),
                        new_distinct: change.new_distinct,
                        gone_distinct: change.gone_distinct,
                        shared_distinct: change.shared_distinct,
                        distinct: change.distinct,
                        capped: change.capped,
                    }
                })
                .collect();
            TemplateChanges { id: template_id(&text), text, positions }
        })
        .collect())
}
