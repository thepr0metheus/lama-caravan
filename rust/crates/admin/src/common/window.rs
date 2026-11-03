//! What counts as a context window, and which nearby numbers must never be taken for one. Three numbers can be found around one model, and only the SERVED one answers "how much may I send in one request": the trained window is a property of the weights, the configured total is the sum across slots. The last two are larger than the truth, and larger is the dangerous direction.

use rules::{Coerce, ContextWindow};
use serde_json::Value;
use wire::Percent;

/// The readings.
pub struct Windows;

impl Windows {
    /// `null` from a vLLM LoRA card is an absence, not a size.
    fn positive(value: Option<&Value>) -> Option<i64> {
        value.filter(|value| !value.is_boolean() && !value.is_null()).and_then(Coerce::int).filter(|number| *number > 0)
    }

    /// The context one request may use, as the SERVER itself reported it: vLLM's `max_model_len`, llama.cpp's `meta.n_ctx`.
    pub fn served(entry: &Value) -> Option<i64> {
        Self::positive(entry.get("max_model_len"))
            .or_else(|| Self::positive(entry.get("meta").filter(|meta| meta.is_object()).and_then(|meta| meta.get("n_ctx"))))
    }

    /// The context one request may use, as a llama.cpp server's /props states it.
    pub fn props_served(props: &Value) -> Option<i64> {
        Self::positive(
            props
                .get("default_generation_settings")
                .filter(|section| section.is_object())
                .and_then(|section| section.get("n_ctx")),
        )
        .or_else(|| Self::positive(props.get("n_ctx")))
    }

    /// The context the WEIGHTS were trained with, as a live server's model card states it: shown beside the model's name and labelled as such, never advertised as a window.
    pub fn trained(entry: &Value) -> Option<i64> {
        Self::positive(entry.get("meta").filter(|meta| meta.is_object()).and_then(|meta| meta.get("n_ctx_train")))
    }

    /// The context a provider's CATALOGUE claims for one of its models.
    pub fn declared(entry: &Value) -> Option<i64> {
        ["context_length", "max_input_tokens", "context_window", "max_model_len"]
            .iter()
            .find_map(|key| Self::positive(entry.get(*key)))
    }

    /// The window a PORT advertises: the smaller of the operator's limit and the model's own size, one rule for the proxy and the board.
    pub fn effective(limit: Option<&Value>, model: Option<&Value>, prefer_model: bool) -> Option<i64> {
        ContextWindow::effective(Self::positive(limit), Self::positive(model), prefer_model)
    }

    /// The operator's two settings on a proxy route: (limit, prefer_model). Zero and rubbish are absences, not limits.
    pub fn route_inputs(route: &Value) -> (Option<i64>, bool) {
        (Self::positive(route.get("contextLength")), Coerce::truthy(route.get("contextAuto")))
    }

    /// The window a cloud POOL stands for. The operator's declared figure is the rule; what the providers report is used ONLY when the operator ticked the pool's switch: a number nobody chose is the same trap as a guessed one.
    pub fn pool(declared: Option<&Value>, reported: Option<i64>, prefer_reported: bool) -> Option<i64> {
        match reported.filter(|reported| prefer_reported && *reported > 0) {
            Some(reported) => Some(reported),
            None => Self::positive(declared),
        }
    }

    /// Where a PORT states its window: (question, path), by what its plain request reaches. Every port answers the model list; a cloud port also retrieve-model; a cell's port also llama.cpp's /props; a port that reaches nothing gets the list alone: that is the answer that says why.
    pub fn paths(upstream_type: &str, model_ids: &[String]) -> Vec<(&'static str, String)> {
        let mut paths = vec![("list", "/v1/models".to_string())];
        if upstream_type == "cloud" {
            paths.extend(
                model_ids
                    .iter()
                    .filter(|id| !id.is_empty())
                    .map(|id| ("retrieve", format!("/v1/models/{}", Percent::encode_keeping(id, "/:@")))),
            );
        } else if upstream_type == "llama" {
            paths.extend(["/props", "/v1/props"].map(|path| ("props", path.to_string())));
        }
        paths
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn each_number_is_read_under_its_own_name() {
        assert_eq!(Windows::served(&json!({"meta": {"n_ctx": 60160, "n_ctx_train": 131072}})), Some(60160));
        assert_eq!(Windows::trained(&json!({"meta": {"n_ctx": 60160, "n_ctx_train": 131072}})), Some(131072));
        assert_eq!(Windows::served(&json!({"max_model_len": null})), None);
        assert_eq!(Windows::props_served(&json!({"default_generation_settings": {"n_ctx": 5}, "n_ctx": 9})), Some(5));
        assert_eq!(Windows::declared(&json!({"max_input_tokens": 7, "context_window": 9})), Some(7));
        assert_eq!(Windows::effective(Some(&json!(100)), Some(&json!(50)), false), Some(50));
        assert_eq!(Windows::effective(Some(&json!(100)), Some(&json!(500)), true), Some(500));
        assert_eq!(Windows::effective(Some(&json!(0)), None, false), None);
        assert_eq!(Windows::pool(Some(&json!(10)), Some(20), false), Some(10));
        assert_eq!(Windows::pool(Some(&json!(10)), Some(20), true), Some(20));
    }

    #[test]
    fn a_port_says_where_its_window_is_read() {
        assert_eq!(Windows::paths("", &[]), [("list", "/v1/models".to_string())]);
        assert_eq!(Windows::paths("llama", &[]).len(), 3);
        assert_eq!(
            Windows::paths("cloud", &["openai/gpt 4".to_string()]).get(1).map(|row| row.1.as_str()),
            Some("/v1/models/openai/gpt%204")
        );
    }
}
