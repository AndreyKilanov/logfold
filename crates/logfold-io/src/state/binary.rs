//! The binary form of a state file.
//!
//! Layout: the magic, the schema version (u16), the algorithm and extension contract versions (u32), four texts, the
//! parameters and the counts (varints), the roots, the nodes, the templates, the overflow templates, and the SHA-256 of
//! all the bytes before it. Texts and byte strings are a varint length and the bytes; templates carry their history
//! (count, first and last time as little-endian i64, one count per level as varints).

use logfold_core::{ClusterHistory, ClusterSnapshot, LEVEL_COUNT, MinerSnapshot, NodeSnapshot};
use sha2::{Digest, Sha256};

use super::wire::{Cursor, StateCounts, counts_of, put_varint};
use super::{
    BINARY_MAGIC, MAX_HEADER_TEXT_BYTES, STATE_SCHEMA_VERSION, State, StateError, StateHeader, StateLimits, damaged,
    over,
};

fn put_bytes(out: &mut Vec<u8>, bytes: &[u8]) {
    put_varint(out, bytes.len() as u64);
    out.extend_from_slice(bytes);
}

fn put_cluster(out: &mut Vec<u8>, cluster: &ClusterSnapshot) {
    put_varint(out, cluster.tokens.len() as u64);
    for token in &cluster.tokens {
        put_bytes(out, token);
    }
    let history = &cluster.history;
    put_varint(out, history.count);
    out.extend_from_slice(&history.first.to_le_bytes());
    out.extend_from_slice(&history.last.to_le_bytes());
    for level in history.levels {
        put_varint(out, level);
    }
}

pub(super) fn encode(state: &State) -> Vec<u8> {
    let snapshot = &state.snapshot;
    let counts = counts_of(snapshot);
    let mut out = Vec::new();
    out.extend_from_slice(BINARY_MAGIC);
    out.extend_from_slice(&(STATE_SCHEMA_VERSION as u16).to_le_bytes());
    out.extend_from_slice(&state.header.algo_version.to_le_bytes());
    out.extend_from_slice(&state.header.contract.to_le_bytes());
    for text in [&state.header.logfold_version, &state.header.config_hash, &state.header.masks, &state.header.format] {
        put_bytes(&mut out, text.as_bytes());
    }
    for value in
        [snapshot.depth as u64, snapshot.threshold_micro, snapshot.max_children as u64, snapshot.max_templates as u64]
    {
        put_varint(&mut out, value);
    }
    for value in [counts.nodes, counts.clusters, counts.overflow, counts.token_bytes] {
        put_varint(&mut out, value);
    }
    put_varint(&mut out, snapshot.roots.len() as u64);
    for &(length, node) in &snapshot.roots {
        put_varint(&mut out, length as u64);
        put_varint(&mut out, u64::from(node));
    }
    for node in &snapshot.nodes {
        put_varint(&mut out, node.children.len() as u64);
        for (key, child) in &node.children {
            put_bytes(&mut out, key);
            put_varint(&mut out, u64::from(*child));
        }
        put_varint(&mut out, node.clusters.len() as u64);
        for &id in &node.clusters {
            put_varint(&mut out, u64::from(id));
        }
    }
    for cluster in &snapshot.clusters {
        put_cluster(&mut out, cluster);
    }
    for (length, cluster) in &snapshot.overflow {
        put_varint(&mut out, *length as u64);
        put_cluster(&mut out, cluster);
    }
    let digest = Sha256::digest(&out);
    out.extend_from_slice(&digest);
    out
}

struct Reader<'a> {
    cursor: Cursor<'a>,
    limits: &'a StateLimits,
    token_bytes: u64,
    declared_token_bytes: u64,
}

impl<'a> Reader<'a> {
    fn text(&mut self) -> Result<String, StateError> {
        let length = self.cursor.count(1, MAX_HEADER_TEXT_BYTES as u64, "a header text")?;
        String::from_utf8(self.cursor.bytes(length)?.to_vec()).map_err(|_| damaged("a header text is not UTF-8"))
    }

    fn size(&mut self, what: &str) -> Result<usize, StateError> {
        usize::try_from(self.cursor.varint()?).map_err(|_| damaged(format!("{what} does not fit the memory")))
    }

    fn token(&mut self) -> Result<Box<[u8]>, StateError> {
        let length = self.cursor.count(1, self.limits.max_token_bytes, "a token")?;
        self.token_bytes += length as u64;
        if self.token_bytes > self.declared_token_bytes {
            return Err(damaged("the tokens are longer than the header says"));
        }
        Ok(Box::from(self.cursor.bytes(length)?))
    }

    fn cluster(&mut self) -> Result<ClusterSnapshot, StateError> {
        let count = self.cursor.count(1, self.limits.max_total_token_bytes, "tokens of a template")?;
        let mut tokens = Vec::with_capacity(count);
        for _ in 0..count {
            tokens.push(self.token()?);
        }
        let mut history = ClusterHistory {
            count: self.cursor.varint()?,
            first: self.cursor.i64_le()?,
            last: self.cursor.i64_le()?,
            ..ClusterHistory::default()
        };
        for slot in history.levels.iter_mut().take(LEVEL_COUNT) {
            *slot = self.cursor.varint()?;
        }
        Ok(ClusterSnapshot { tokens, history })
    }
}

pub(super) fn decode(bytes: &[u8], limits: &StateLimits) -> Result<State, StateError> {
    if bytes.len() < BINARY_MAGIC.len() + 2 {
        return Err(damaged("the file is too short"));
    }
    let Some([low, high]) = bytes.get(BINARY_MAGIC.len()..BINARY_MAGIC.len() + 2) else {
        return Err(damaged("the file is too short"));
    };
    let schema = u32::from(u16::from_le_bytes([*low, *high]));
    if schema > STATE_SCHEMA_VERSION {
        return Err(StateError::Version { found: schema, supported: STATE_SCHEMA_VERSION });
    }
    if bytes.len() < BINARY_MAGIC.len() + 2 + 32 {
        return Err(damaged("the file is too short"));
    }
    let (body, digest) = bytes.split_at(bytes.len() - 32);
    if Sha256::digest(body).as_slice() != digest {
        return Err(StateError::Checksum);
    }
    let mut cursor = Cursor::new(body.get(BINARY_MAGIC.len()..).ok_or_else(|| damaged("the file is too short"))?);
    cursor.u16_le()?;
    let algo_version = cursor.u32_le()?;
    let contract = cursor.u32_le()?;
    let mut reader = Reader { cursor, limits, token_bytes: 0, declared_token_bytes: 0 };
    let header = StateHeader {
        algo_version,
        contract,
        logfold_version: reader.text()?,
        config_hash: reader.text()?,
        masks: reader.text()?,
        format: reader.text()?,
    };
    let depth = reader.size("depth")?;
    let threshold_micro = reader.cursor.varint()?;
    let max_children = reader.size("max_children")?;
    let max_templates = reader.size("max_templates")?;
    let counts = StateCounts {
        nodes: reader.cursor.varint()?,
        clusters: reader.cursor.varint()?,
        overflow: reader.cursor.varint()?,
        token_bytes: reader.cursor.varint()?,
    };
    check_counts(&counts, limits)?;
    reader.declared_token_bytes = counts.token_bytes;

    let root_count = reader.cursor.count(2, limits.max_nodes, "roots")?;
    let mut roots = Vec::with_capacity(root_count);
    for _ in 0..root_count {
        let length = reader.size("a message length")?;
        let node = u32::try_from(reader.cursor.varint()?).map_err(|_| damaged("a node id does not fit 32 bits"))?;
        roots.push((length, node));
    }
    let mut nodes = Vec::with_capacity(bounded(counts.nodes, reader.cursor.remaining(), 2));
    for _ in 0..counts.nodes {
        let child_count = reader.cursor.count(2, limits.max_nodes, "children of a node")?;
        let mut children = Vec::with_capacity(child_count);
        for _ in 0..child_count {
            let key = reader.token()?;
            let child =
                u32::try_from(reader.cursor.varint()?).map_err(|_| damaged("a node id does not fit 32 bits"))?;
            children.push((key, child));
        }
        let id_count = reader.cursor.count(1, limits.max_clusters, "templates of a leaf")?;
        let mut ids = Vec::with_capacity(id_count);
        for _ in 0..id_count {
            ids.push(
                u32::try_from(reader.cursor.varint()?).map_err(|_| damaged("a template id does not fit 32 bits"))?,
            );
        }
        nodes.push(NodeSnapshot { children, clusters: ids });
    }
    let mut clusters = Vec::with_capacity(bounded(counts.clusters, reader.cursor.remaining(), 10));
    for _ in 0..counts.clusters {
        clusters.push(reader.cluster()?);
    }
    let mut overflow = Vec::with_capacity(bounded(counts.overflow, reader.cursor.remaining(), 10));
    for _ in 0..counts.overflow {
        let length = reader.size("an overflow length")?;
        overflow.push((length, reader.cluster()?));
    }
    if !reader.cursor.finished() {
        return Err(damaged("bytes after the last value"));
    }
    if reader.token_bytes != counts.token_bytes {
        return Err(damaged("the tokens are shorter than the header says"));
    }
    let snapshot =
        MinerSnapshot { depth, threshold_micro, max_children, max_templates, nodes, roots, clusters, overflow };
    Ok(State { header, snapshot })
}

/// Capacity to reserve for `declared` items of at least `min_bytes` each: never more than the data can hold.
fn bounded(declared: u64, remaining: usize, min_bytes: usize) -> usize {
    declared.min((remaining / min_bytes) as u64) as usize
}

pub(super) fn check_counts(counts: &StateCounts, limits: &StateLimits) -> Result<(), StateError> {
    if counts.nodes > limits.max_nodes {
        return Err(over(format!("{} nodes, at most {}", counts.nodes, limits.max_nodes)));
    }
    let templates = counts.clusters.saturating_add(counts.overflow);
    if templates > limits.max_clusters {
        return Err(over(format!("{templates} templates, at most {}", limits.max_clusters)));
    }
    if counts.token_bytes > limits.max_total_token_bytes {
        return Err(over(format!("{} bytes of tokens, at most {}", counts.token_bytes, limits.max_total_token_bytes)));
    }
    Ok(())
}
