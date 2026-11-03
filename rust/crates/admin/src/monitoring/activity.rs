//! The requests in flight and just finished, by route, from the proxy's own records.

use crate::proxies::stats::ProxyStats;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

/// What the monitor says of the requests.
pub struct Activity;

impl Activity {
    fn sorted_words<'rows>(rows: impl Iterator<Item = &'rows Value>, key: &str) -> Vec<Value> {
        let words: BTreeSet<String> = rows
            .filter_map(|item| item.get(key))
            .filter(|said| Coerce::truthy(Some(*said)))
            .map(|said| Coerce::str_of(Some(said)))
            .collect();
        words.into_iter().map(Value::String).collect()
    }

    fn items_of(label: &str, row: &Value, key: &str, state: &str, correlation: &str) -> Vec<Value> {
        let rows = row.get(key).and_then(Value::as_array).into_iter().flatten().filter(|item| item.is_object());
        rows.map(|item| {
            let mut shown = ProxyStats::summarize_item(label, row, item, state);
            let kind = {
                let said = item
                    .get("upstreamType")
                    .filter(|said| Coerce::truthy(Some(*said)))
                    .or_else(|| row.get("upstreamType").filter(|said| Coerce::truthy(Some(*said))));
                said.map_or_else(|| "llama".to_string(), |said| Coerce::str_of(Some(said)))
            };
            Coerce::put(&mut shown, "correlation", json!(correlation));
            Coerce::put(&mut shown, "isCloud", json!(kind == "cloud"));
            shown
        })
        .collect()
    }

    /// A route's requests, on the lists of all of them and in its own row.
    fn one_route(key: &str, row: &Value, books: (&mut Vec<Value>, &mut Vec<Value>, &mut Map<String, Value>)) {
        let (active, recent, by_proxy) = books;
        let label = {
            let said = Coerce::stripped(row.get("label"));
            let said = if said.is_empty() { Coerce::strip(key).to_string() } else { said };
            if said.is_empty() { key.to_string() } else { said }
        };
        let route_active = Self::items_of(&label, row, "active", "active", "active-proxy");
        let route_recent = Self::items_of(&label, row, "recent", "recent", "proxy-only");
        let tail = route_recent.iter().skip(route_recent.len().saturating_sub(8)).cloned().collect::<Vec<_>>();
        let last = route_active.last().or_else(|| route_recent.last()).cloned().unwrap_or(Value::Null);
        by_proxy.insert(
            label.clone(),
            json!({
                "label": label, "port": row.get("port"), "upstream": row.get("upstream"),
                "upstreamType": row.get("upstreamType").cloned().unwrap_or_else(|| json!("llama")),
                "active": route_active, "recent": tail, "last": last,
            }),
        );
        active.extend(route_active);
        recent.extend(route_recent);
    }

    /// The picture of one sample.
    pub fn correlate(sample: &Value) -> Value {
        let empty = json!({});
        let gpu = sample.get("gpu").filter(|said| said.is_object()).unwrap_or(&empty);
        let agents = sample.get("agentProxies").and_then(|proxies| proxies.get("agents")).and_then(Value::as_object);
        let (mut active, mut recent, mut by_proxy) = (Vec::new(), Vec::new(), Map::new());
        for (key, row) in agents.into_iter().flatten() {
            Self::one_route(key, row, (&mut active, &mut recent, &mut by_proxy));
        }
        let is_cloud = |item: &&Value| Coerce::truthy(item.get("isCloud"));
        let not_cloud = |item: &&Value| !Coerce::truthy(item.get("isCloud"));
        let llama_count = active.iter().filter(not_cloud).count();
        // absent-ok: `item.get("finishedAt") or item.get("startedAt") or 0`: a request with no moment is the oldest.
        let moment = |item: &Value| {
            item.get("finishedAt")
                .filter(|at| Coerce::truthy(Some(*at)))
                .or_else(|| item.get("startedAt"))
                .and_then(Coerce::float)
                // absent-ok: a figure not said is none.
                .unwrap_or(0.0)
        };
        recent.sort_by(|left, right| moment(right).total_cmp(&moment(left)));
        recent.truncate(20);
        let gpu_at = |key: &str| gpu.get(key).cloned();
        json!({
            "ok": true,
            "time": sample.get("time"),
            "activeRequests": active,
            "recentRequests": recent,
            "byProxy": by_proxy,
            "llamaServer": {
                "activeRequestCount": llama_count,
                "activeClients": Self::sorted_words(active.iter().filter(not_cloud), "client"),
                "activeRoutes": Self::sorted_words(active.iter().filter(not_cloud), "label"),
            },
            "gpu": {
                "activeRequestCount": active.len(),
                "activeClients": Self::sorted_words(active.iter(), "client"),
                "activeRoutes": Self::sorted_words(active.iter().filter(not_cloud), "label"),
                "cloudActiveRoutes": Self::sorted_words(active.iter().filter(is_cloud), "label"),
                "utilPct": gpu_at("utilPct").unwrap_or_else(|| json!(0)),
                "memoryPct": gpu_at("memoryPct").unwrap_or_else(|| json!(0)),
                "memoryUsedMiB": gpu_at("memoryUsedMiB"),
                "memoryTotalMiB": gpu_at("memoryTotalMiB"),
                "temperatureC": gpu_at("temperatureC"),
                "powerW": gpu_at("powerW"),
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_sample_says_what_runs_and_where() {
        let sample = json!({"time": 5, "gpu": {"utilPct": 7}, "agentProxies": {"agents": {"1": {"label": "L", "port": 1, "upstreamType": "cloud",
            "active": [{"id": "a", "client": "c"}], "recent": [{"id": "b", "finishedAt": 1}, {"id": "d", "finishedAt": 2, "upstreamType": "llama"}]}}}});
        let shown = Activity::correlate(&sample);
        assert_eq!(shown["activeRequests"][0]["isCloud"], true);
        assert_eq!(shown["recentRequests"][0]["id"], "d");
        assert_eq!(shown["gpu"]["cloudActiveRoutes"], json!(["L"]));
        assert_eq!(shown["gpu"]["activeRoutes"], json!([]));
        assert_eq!(shown["llamaServer"]["activeRequestCount"], 0);
        assert_eq!(shown["gpu"]["utilPct"], 7);
        assert_eq!(shown["byProxy"]["L"]["last"]["id"], "a");
    }
}
