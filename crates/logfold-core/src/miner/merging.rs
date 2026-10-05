//! Merging of miners: the chunked strategy folds the tree of every chunk into one (`docs/ALGORITHM.md` §6).

use super::matching::BoxedTokens;
use super::{Cluster, DrainMiner, RunStats, WILDCARD};

impl DrainMiner {
    /// Copy of the tree with empty statistics: the start of a worker that continues a seed tree.
    pub fn warm_copy(&self) -> DrainMiner {
        let mut copy = self.clone();
        let blank = vec![RunStats::default(); self.n_runs];
        for cluster in &mut copy.clusters {
            cluster.stats = blank.clone();
        }
        copy.overflow.clear();
        copy.overflowed = vec![false; self.n_runs];
        copy
    }

    /// Merges a worker tree that started as a [`DrainMiner::warm_copy`] of the seed of `self`.
    ///
    /// The first `seed_len` clusters are the seed's: they are generalized position by position and their statistics
    /// absorbed; the others are merged like in [`DrainMiner::merge`].
    pub fn merge_warm(&mut self, other: DrainMiner, seed_len: usize) {
        assert_eq!(self.n_runs, other.n_runs, "miners must track the same runs");
        for (mine, theirs) in self.overflowed.iter_mut().zip(other.overflowed.iter()) {
            *mine |= *theirs;
        }
        for (index, cluster) in other.clusters.into_iter().enumerate() {
            if index < seed_len {
                let mine = &mut self.clusters[index];
                for (position, token) in cluster.tokens.iter().enumerate() {
                    let current = &mine.tokens[position];
                    if &**current != WILDCARD && (&**token == WILDCARD || **token != **current) {
                        mine.tokens[position] = Box::from(WILDCARD);
                        mine.wild += 1;
                    }
                }
                for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                    dst.absorb(src);
                }
            } else {
                self.merge_cluster(cluster);
            }
        }
        for (length, cluster) in other.overflow {
            match self.overflow.get_mut(&length) {
                Some(mine) => {
                    for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                        dst.absorb(src);
                    }
                }
                None => {
                    self.overflow.insert(length, cluster);
                }
            }
        }
    }

    /// Merges `other` into `self` in cluster creation order (see `docs/ALGORITHM.md` §6).
    pub fn merge(&mut self, other: DrainMiner) {
        assert_eq!(self.n_runs, other.n_runs, "miners must track the same runs");
        for (mine, theirs) in self.overflowed.iter_mut().zip(other.overflowed.iter()) {
            *mine |= *theirs;
        }
        for cluster in other.clusters {
            self.merge_cluster(cluster);
        }
        for (length, cluster) in other.overflow {
            match self.overflow.get_mut(&length) {
                Some(mine) => {
                    for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                        dst.absorb(src);
                    }
                }
                None => {
                    self.overflow.insert(length, cluster);
                }
            }
        }
    }

    fn merge_cluster(&mut self, cluster: Cluster) {
        let matched = self.find_match(&BoxedTokens(&cluster.tokens));
        match matched {
            Some(index) => {
                self.generalize(index, &BoxedTokens(&cluster.tokens));
                for (dst, src) in self.clusters[index].stats.iter_mut().zip(cluster.stats.iter()) {
                    dst.absorb(src);
                }
            }
            None => self.insert_cluster(cluster),
        }
    }
}
