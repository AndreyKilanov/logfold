//! The distributions of the values of the most frequent templates, collected in the pass that assigns records to the
//! finished tree (ADR-016).

use std::collections::{BTreeMap, HashMap};

use logfold_core::{
    Assignment, Distribution, DrainMiner, Fit, RecordMeta, Recount, Slot, TokenView, ValueCollector, WILDCARD_NAME,
    default_mask_rules, extract_parameters, template_id,
};

use crate::pipeline::PipelineContext;
use crate::types::{PositionValues, TemplateValues, ValuesRequest};

/// The templates whose values are collected, with their tokens.
pub(crate) struct ValuePlan {
    templates: HashMap<u32, Vec<Box<[u8]>>>,
    /// The names of the rules whose values are collected: the default rules. A value that a mask set of the user hides
    /// (a key, an e-mail address) is never counted, so a report cannot show it.
    names: Vec<String>,
}

impl ValuePlan {
    /// Picks the `request.templates` most frequent clusters of `miner`.
    pub(crate) fn new(miner: &DrainMiner, request: ValuesRequest) -> Self {
        let templates = miner
            .top_clusters(request.templates)
            .into_iter()
            .map(|index| (index, miner.cluster_tokens(index).to_vec()))
            .collect();
        ValuePlan { templates, names: default_mask_rules().into_iter().map(|rule| rule.name).collect() }
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

/// A recount for `n_runs` runs that also collects the values when there is a plan.
pub(crate) fn new_recount(n_runs: usize, rule: logfold_core::MatchRule, plan: Option<&ValuePlan>) -> Recount {
    let recount = Recount::with_rule(n_runs, rule);
    if plan.is_some() { recount.with_values() } else { recount }
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
