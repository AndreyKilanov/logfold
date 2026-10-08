//! The JSON form of a state file.
//!
//! Three lines: the header, the body, and `{"sha256":"..."}` with the SHA-256 of the two lines before it (their line
//! feeds included). The text is compact and written by hand in a fixed order, so the same state is the same bytes in
//! every engine; no number is a float. A token is a JSON string, or `{"hex":"..."}` when its bytes are not UTF-8.
//! Reading is bounded: the header is checked against the limits before the body is parsed, and the body is read with
//! bounded sequences.

use std::fmt;
use std::marker::PhantomData;

use logfold_core::{ClusterSnapshot, History, MinerSnapshot, NodeSnapshot};
use serde::Deserialize;
use serde::de::{self, DeserializeSeed, Deserializer, MapAccess, SeqAccess, Visitor};
use sha2::{Digest, Sha256};

use super::binary::check_counts;
use super::wire::{StateCounts, counts_of, from_hex, to_hex};
use super::{
    MAX_HEADER_TEXT_BYTES, STATE_KIND, STATE_SCHEMA_VERSION, State, StateError, StateHeader, StateLimits, damaged, over,
};

const LIMIT_MARK: &str = "state limit: ";

fn put_text(out: &mut Vec<u8>, text: &str) {
    serde_json::to_writer(&mut *out, text).expect("a string always serializes");
}

fn put_token(out: &mut Vec<u8>, token: &[u8]) {
    match std::str::from_utf8(token) {
        Ok(text) => put_text(out, text),
        Err(_) => {
            out.extend_from_slice(br#"{"hex":""#);
            out.extend_from_slice(to_hex(token).as_bytes());
            out.extend_from_slice(b"\"}");
        }
    }
}

fn put_number(out: &mut Vec<u8>, value: impl fmt::Display) {
    out.extend_from_slice(value.to_string().as_bytes());
}

fn put_cluster(out: &mut Vec<u8>, cluster: &ClusterSnapshot) {
    out.extend_from_slice(br#"{"t":["#);
    for (index, token) in cluster.tokens.iter().enumerate() {
        if index > 0 {
            out.push(b',');
        }
        put_token(out, token);
    }
    let h = &cluster.history;
    out.extend_from_slice(br#"],"h":["#);
    put_number(out, h.count);
    out.push(b',');
    put_number(out, h.first);
    out.push(b',');
    put_number(out, h.last);
    out.extend_from_slice(b",[");
    for (index, level) in h.levels.iter().enumerate() {
        if index > 0 {
            out.push(b',');
        }
        put_number(out, level);
    }
    out.extend_from_slice(b"]]}");
}

fn put_list<T>(out: &mut Vec<u8>, items: &[T], mut each: impl FnMut(&mut Vec<u8>, &T)) {
    out.push(b'[');
    for (index, item) in items.iter().enumerate() {
        if index > 0 {
            out.push(b',');
        }
        each(out, item);
    }
    out.push(b']');
}

pub(super) fn encode(state: &State) -> Vec<u8> {
    let snapshot = &state.snapshot;
    let counts = counts_of(snapshot);
    let header = &state.header;
    let mut out = Vec::new();
    out.extend_from_slice(format!(r#"{{"kind":"{STATE_KIND}","schema_version":{STATE_SCHEMA_VERSION},"#).as_bytes());
    out.extend_from_slice(
        format!(r#""algo_version":{},"contract":{},"logfold_version":"#, header.algo_version, header.contract)
            .as_bytes(),
    );
    put_text(&mut out, &header.logfold_version);
    out.extend_from_slice(br#","config_hash":"#);
    put_text(&mut out, &header.config_hash);
    out.extend_from_slice(br#","masks":"#);
    put_text(&mut out, &header.masks);
    out.extend_from_slice(br#","format":"#);
    put_text(&mut out, &header.format);
    out.extend_from_slice(
        format!(
            r#","miner":{{"depth":{},"threshold_micro":{},"max_children":{},"max_templates":{}}},"counts":{{"nodes":{},"clusters":{},"overflow":{},"token_bytes":{}}}}}"#,
            snapshot.depth,
            snapshot.threshold_micro,
            snapshot.max_children,
            snapshot.max_templates,
            counts.nodes,
            counts.clusters,
            counts.overflow,
            counts.token_bytes
        )
        .as_bytes(),
    );
    out.push(b'\n');

    out.extend_from_slice(br#"{"nodes":"#);
    put_list(&mut out, &snapshot.nodes, |out, node| {
        out.extend_from_slice(br#"{"c":"#);
        put_list(out, &node.children, |out, (key, child)| {
            out.push(b'[');
            put_token(out, key);
            out.push(b',');
            put_number(out, child);
            out.push(b']');
        });
        out.extend_from_slice(br#","k":"#);
        put_list(out, &node.clusters, |out, id| put_number(out, id));
        out.push(b'}');
    });
    out.extend_from_slice(br#","roots":"#);
    put_list(&mut out, &snapshot.roots, |out, (length, node)| {
        out.push(b'[');
        put_number(out, length);
        out.push(b',');
        put_number(out, node);
        out.push(b']');
    });
    out.extend_from_slice(br#","clusters":"#);
    put_list(&mut out, &snapshot.clusters, put_cluster);
    out.extend_from_slice(br#","overflow":"#);
    put_list(&mut out, &snapshot.overflow, |out, (length, cluster)| {
        out.push(b'[');
        put_number(out, length);
        out.push(b',');
        put_cluster(out, cluster);
        out.push(b']');
    });
    out.extend_from_slice(b"}\n");

    let digest = to_hex(&Sha256::digest(&out));
    out.extend_from_slice(format!("{{\"sha256\":\"{digest}\"}}\n").as_bytes());
    out
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeaderJson {
    kind: String,
    schema_version: u32,
    algo_version: u32,
    contract: u32,
    logfold_version: String,
    config_hash: String,
    masks: String,
    format: String,
    miner: MinerJson,
    counts: CountsJson,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MinerJson {
    depth: u64,
    threshold_micro: u64,
    max_children: u64,
    max_templates: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CountsJson {
    nodes: u64,
    clusters: u64,
    overflow: u64,
    token_bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrailerJson {
    sha256: String,
}

/// A token: a string, or an object with the hex of bytes that are not UTF-8.
struct Token(Box<[u8]>);

impl<'de> Deserialize<'de> for Token {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct TokenVisitor;
        impl<'de> Visitor<'de> for TokenVisitor {
            type Value = Token;

            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a token: a string or an object with \"hex\"")
            }

            fn visit_str<E: de::Error>(self, text: &str) -> Result<Token, E> {
                Ok(Token(Box::from(text.as_bytes())))
            }

            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Token, A::Error> {
                let Some((key, value)) = map.next_entry::<String, String>()? else {
                    return Err(de::Error::custom("an empty token object"));
                };
                if key != "hex" || map.next_key::<String>()?.is_some() {
                    return Err(de::Error::custom("a token object has only \"hex\""));
                }
                let bytes = from_hex(&value).map_err(|error| de::Error::custom(error.to_string()))?;
                Ok(Token(bytes.into_boxed_slice()))
            }
        }
        deserializer.deserialize_any(TokenVisitor)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NodeJson {
    c: Vec<(Token, u32)>,
    k: Vec<u32>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ClusterJson {
    t: Vec<Token>,
    h: (u64, i64, i64, [u64; 6]),
}

impl ClusterJson {
    fn into_snapshot(self) -> ClusterSnapshot {
        let (count, first, last, levels) = self.h;
        ClusterSnapshot {
            tokens: self.t.into_iter().map(|token| token.0).collect(),
            history: History { count, first, last, levels },
        }
    }
}

/// A sequence that stops with a limit error as soon as it holds more than `max` items.
struct Bounded<T> {
    max: u64,
    what: &'static str,
    items: PhantomData<T>,
}

impl<T> Bounded<T> {
    fn new(max: u64, what: &'static str) -> Self {
        Bounded { max, what, items: PhantomData }
    }
}

impl<'de, T: Deserialize<'de>> DeserializeSeed<'de> for Bounded<T> {
    type Value = Vec<T>;

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Vec<T>, D::Error> {
        deserializer.deserialize_seq(self)
    }
}

impl<'de, T: Deserialize<'de>> Visitor<'de> for Bounded<T> {
    type Value = Vec<T>;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a list")
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Vec<T>, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = seq.next_element::<T>()? {
            if items.len() as u64 >= self.max {
                return Err(de::Error::custom(format!("{LIMIT_MARK}more than {} {}", self.max, self.what)));
            }
            items.push(item);
        }
        Ok(items)
    }
}

struct Body {
    nodes: Vec<NodeJson>,
    roots: Vec<(u64, u32)>,
    clusters: Vec<ClusterJson>,
    overflow: Vec<(u64, ClusterJson)>,
}

struct BodySeed<'a>(&'a StateLimits);

impl<'de> DeserializeSeed<'de> for BodySeed<'_> {
    type Value = Body;

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Body, D::Error> {
        deserializer.deserialize_map(self)
    }
}

impl<'de> Visitor<'de> for BodySeed<'_> {
    type Value = Body;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("the body of a state file")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Body, A::Error> {
        let limits = self.0;
        let (mut nodes, mut roots, mut clusters, mut overflow) = (None, None, None, None);
        while let Some(key) = map.next_key::<String>()? {
            match key.as_str() {
                "nodes" if nodes.is_none() => {
                    nodes = Some(map.next_value_seed(Bounded::new(limits.max_nodes, "nodes"))?)
                }
                "roots" if roots.is_none() => {
                    roots = Some(map.next_value_seed(Bounded::new(limits.max_nodes, "roots"))?)
                }
                "clusters" if clusters.is_none() => {
                    clusters = Some(map.next_value_seed(Bounded::new(limits.max_clusters, "templates"))?);
                }
                "overflow" if overflow.is_none() => {
                    overflow = Some(map.next_value_seed(Bounded::new(limits.max_clusters, "overflow templates"))?);
                }
                other => return Err(de::Error::custom(format!("unexpected or repeated field '{other}'"))),
            }
        }
        match (nodes, roots, clusters, overflow) {
            (Some(nodes), Some(roots), Some(clusters), Some(overflow)) => Ok(Body { nodes, roots, clusters, overflow }),
            _ => Err(de::Error::custom("the body lacks a field")),
        }
    }
}

fn parse_error(error: serde_json::Error) -> StateError {
    let text = error.to_string();
    match text.strip_prefix(LIMIT_MARK) {
        Some(rest) => over(rest.split(" at line ").next().unwrap_or(rest).to_string()),
        None => damaged(text),
    }
}

fn narrow(value: u64, what: &str) -> Result<usize, StateError> {
    usize::try_from(value).map_err(|_| damaged(format!("{what} does not fit the memory")))
}

fn check_text(text: &str, what: &str) -> Result<(), StateError> {
    if text.len() > MAX_HEADER_TEXT_BYTES {
        return Err(over(format!("{what} is longer than {MAX_HEADER_TEXT_BYTES} bytes")));
    }
    Ok(())
}

pub(super) fn decode(bytes: &[u8], limits: &StateLimits) -> Result<State, StateError> {
    let lines: Vec<&[u8]> = bytes.split(|&byte| byte == b'\n').collect();
    if lines.len() != 4 || !lines[3].is_empty() {
        return Err(damaged("a JSON state file has three lines: the header, the body and the checksum"));
    }
    let trailer: TrailerJson = serde_json::from_slice(lines[2]).map_err(parse_error)?;
    let signed = lines[0].len() + lines[1].len() + 2;
    if to_hex(&Sha256::digest(&bytes[..signed])) != trailer.sha256 {
        return Err(StateError::Checksum);
    }
    let header: HeaderJson = serde_json::from_slice(lines[0]).map_err(parse_error)?;
    if header.kind != STATE_KIND {
        return Err(StateError::NotState);
    }
    if header.schema_version > STATE_SCHEMA_VERSION {
        return Err(StateError::Version { found: header.schema_version, supported: STATE_SCHEMA_VERSION });
    }
    for (text, what) in [
        (&header.logfold_version, "logfold_version"),
        (&header.config_hash, "config_hash"),
        (&header.masks, "masks"),
        (&header.format, "format"),
    ] {
        check_text(text, what)?;
    }
    let counts = StateCounts {
        nodes: header.counts.nodes,
        clusters: header.counts.clusters,
        overflow: header.counts.overflow,
        token_bytes: header.counts.token_bytes,
    };
    check_counts(&counts, limits)?;

    let body =
        BodySeed(limits).deserialize(&mut serde_json::Deserializer::from_slice(lines[1])).map_err(parse_error)?;
    let nodes: Vec<NodeSnapshot> = body
        .nodes
        .into_iter()
        .map(|node| NodeSnapshot {
            children: node.c.into_iter().map(|(key, child)| (key.0, child)).collect(),
            clusters: node.k,
        })
        .collect();
    let mut roots = Vec::with_capacity(body.roots.len());
    for (length, node) in body.roots {
        roots.push((narrow(length, "a message length")?, node));
    }
    let clusters: Vec<ClusterSnapshot> = body.clusters.into_iter().map(ClusterJson::into_snapshot).collect();
    let mut overflow = Vec::with_capacity(body.overflow.len());
    for (length, cluster) in body.overflow {
        overflow.push((narrow(length, "an overflow length")?, cluster.into_snapshot()));
    }
    let snapshot = MinerSnapshot {
        depth: narrow(header.miner.depth, "depth")?,
        threshold_micro: header.miner.threshold_micro,
        max_children: narrow(header.miner.max_children, "max_children")?,
        max_templates: narrow(header.miner.max_templates, "max_templates")?,
        nodes,
        roots,
        clusters,
        overflow,
    };
    let found = counts_of(&snapshot);
    if found != counts {
        return Err(damaged("the counts in the header are not the counts of the body"));
    }
    let longest = snapshot
        .nodes
        .iter()
        .flat_map(|node| node.children.iter().map(|(key, _)| key.len()))
        .chain(
            snapshot
                .clusters
                .iter()
                .chain(snapshot.overflow.iter().map(|(_, c)| c))
                .flat_map(|c| c.tokens.iter().map(|t| t.len())),
        )
        .max()
        .unwrap_or(0);
    if longest as u64 > limits.max_token_bytes {
        return Err(over(format!("a token of {longest} bytes, at most {}", limits.max_token_bytes)));
    }
    let header = StateHeader {
        algo_version: header.algo_version,
        contract: header.contract,
        logfold_version: header.logfold_version,
        config_hash: header.config_hash,
        masks: header.masks,
        format: header.format,
    };
    Ok(State { header, snapshot })
}
