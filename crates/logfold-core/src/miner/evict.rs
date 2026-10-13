//! Eviction of the least recently used templates, for a miner that keeps learning at its template limit.

use super::leaf::renumber;
use super::{Cluster, DrainMiner, WILDCARD};

/// One template in this many (at least one) is evicted each time the limit is reached, so that the cost of rebuilding the
/// lists of the tree is shared by many new templates.
const EVICT_DIVISOR: usize = 10;

impl DrainMiner {
    /// Drops the least recently used templates and pools their counts, to make room for new templates.
    ///
    /// The templates with the oldest `last_used` go (ties: the earlier created), a tenth of `max_templates` at a time. The
    /// shape of the tree does not change: the clusters are removed from the leaves and the others are renumbered in the
    /// order they were created. The counts of an evicted template, and the counts that a loaded state held for it, join the
    /// catch-all template of its token count, so the totals still add up.
    pub(super) fn evict_stalest(&mut self) {
        let total = self.clusters.len();
        let count = (self.cfg.max_templates / EVICT_DIVISOR).max(1).min(total);
        if count == 0 {
            return;
        }
        let mut order: Vec<u32> = (0..total as u32).collect();
        order.select_nth_unstable_by_key(count - 1, |&id| (self.clusters[id as usize].last_used, id));
        let mut doomed = vec![false; total];
        for &id in &order[..count] {
            doomed[id as usize] = true;
        }
        self.remove_clusters(&doomed);
    }

    fn remove_clusters(&mut self, doomed: &[bool]) {
        let old = std::mem::take(&mut self.clusters);
        let mut new_id = vec![u32::MAX; old.len()];
        let mut kept: Vec<Cluster> = Vec::with_capacity(old.len());
        let mut reported = 0;
        for (id, cluster) in old.into_iter().enumerate() {
            if doomed[id] {
                self.pool(cluster);
            } else {
                new_id[id] = kept.len() as u32;
                reported += usize::from(id < self.reported);
                kept.push(cluster);
            }
        }
        self.clusters = kept;
        self.reported = reported;
        for node in &mut self.nodes {
            renumber(&mut node.clusters, &new_id);
            if let Some(index) = node.index.as_mut() {
                index.renumber(&new_id);
            }
        }
        for list in self.length_clusters.values_mut() {
            renumber(list, &new_id);
        }
        self.length_clusters.retain(|_, list| !list.is_empty());
        for group in self.length_indexes.values_mut() {
            renumber(&mut group.sparse, &new_id);
            if let Some(index) = group.index.get_mut() {
                index.renumber(&new_id);
            }
        }
    }

    fn pool(&mut self, cluster: Cluster) {
        self.evicted[self.run] += 1;
        let length = cluster.tokens.len();
        for (run, stats) in cluster.stats.iter().enumerate() {
            if stats.count > 0 {
                self.overflowed[run] = true;
            }
        }
        match self.overflow.get_mut(&length) {
            Some(mine) => {
                for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                    dst.absorb(src);
                }
                mine.history.absorb(&cluster.history);
            }
            None => {
                let tokens = (0..length).map(|_| Box::from(WILDCARD)).collect();
                let mut pooled = Cluster::new(tokens, cluster.stats);
                pooled.history = cluster.history;
                self.overflow.insert(length, pooled);
            }
        }
    }
}
