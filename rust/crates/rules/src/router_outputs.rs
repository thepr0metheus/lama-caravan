//! The routers' outputs as the controller last wrote them: what a pool's row stands on, and a machine's model with its address.

use crate::coerce::Coerce;
use crate::upstream_type::UpstreamType;
use serde_json::Value;

/// What an output of a router says of the model behind it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RouterOutput {
    /// Its id: `mm:…`, `srv:…`, `eng:…`.
    pub id: String,
    /// Whether `jobs` holds anything at all: a word that is no job is still a word, and it makes a pool's kind mixed, not unknown.
    pub says_its_work: bool,
    /// The jobs it names.
    pub jobs: Vec<String>,
    /// A chat's inputs.
    pub inputs: Vec<String>,
    /// The languages an ear hears, or a translating ear writes.
    pub languages: Vec<String>,
    /// The longest recording it takes.
    pub max_audio_ms: Option<i64>,
    /// The window it serves, as its model said it.
    pub window: Option<i64>,
    /// The model it calls, as the board names it.
    pub model: String,
    /// The machine it stands on.
    pub host: String,
    /// What it takes to call it, when it is a machine's model and this process can read that.
    pub machine: Option<MachineOutput>,
}

impl RouterOutput {
    /// The words of a list field; what is not a string is no word.
    fn words(raw: &Value, field: &str) -> Vec<String> {
        raw.get(field).and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).map(str::to_string).collect()
    }

    /// A number that is a whole size: `ModelKind._positive`, which takes no text.
    fn whole_size(raw: &Value, field: &str) -> Option<i64> {
        raw.get(field).and_then(Value::as_i64).filter(|size| *size > 0)
    }

    fn read(raw: &Value) -> Option<Self> {
        let id = raw.get("id").and_then(Value::as_str)?;
        Some(Self {
            id: id.to_string(),
            says_its_work: Coerce::truthy(raw.get("jobs")),
            jobs: Self::words(raw, "jobs"),
            inputs: Self::words(raw, "inputs"),
            languages: Self::words(raw, "languages"),
            max_audio_ms: Self::whole_size(raw, "maxAudioMs"),
            window: Coerce::positive(raw.get("contextLength")),
            model: Coerce::text(raw.get("upstreamModel")),
            host: Coerce::text(raw.get("hostId")),
            machine: MachineOutput::read(raw),
        })
    }
}

/// The outputs of every router, the first of an id answering for it: `router_output`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RouterOutputs {
    outputs: Vec<RouterOutput>,
}

impl RouterOutputs {
    /// Every output of `routers`, the settings' list, as raw values in their order.
    pub fn raw(routers: Option<&Value>) -> impl Iterator<Item = &Value> {
        let routers = routers.and_then(Value::as_array).into_iter().flatten();
        routers
            .flat_map(|router| router.get("outputs").and_then(Value::as_array).into_iter().flatten())
            .filter(|out| out.is_object())
    }

    /// Every output with an address this process can call.
    pub fn callable(&self) -> impl Iterator<Item = &MachineOutput> {
        self.outputs.iter().filter_map(|output| output.machine.as_ref())
    }

    /// The reading of `routers`.
    pub fn read(routers: Option<&Value>) -> Self {
        let mut read = Self::default();
        for output in Self::raw(routers).filter_map(RouterOutput::read) {
            if read.get(&output.id).is_none() {
                read.outputs.push(output);
            }
        }
        read
    }

    /// The output of `id`.
    pub fn get(&self, id: &str) -> Option<&RouterOutput> {
        self.outputs.iter().find(|output| output.id == id)
    }
}

/// A machine's model as the controller last wrote it on a router's output, with what it takes to call it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MachineOutput {
    /// The output's id: `mm:…`.
    pub id: String,
    /// The name its output gives it.
    pub name: String,
    /// The output's own name on the board.
    pub label: String,
    /// The machine.
    pub host: String,
    /// The address of the machine's entry.
    pub upstream_host: String,
    /// The port of the machine's entry.
    pub upstream_port: u16,
    /// The ports of its running copies: its spare way, each asked once when the entry does not answer.
    pub copy_ports: Vec<u16>,
    /// Whether the board knows it stands still.
    pub stopped: bool,
    /// What stands behind the address.
    pub kind: UpstreamType,
}

impl MachineOutput {
    /// The queue's name, `route_group_key`: one queue per model of a machine's entry, whose port serves them all, and one per server of any other kind.
    pub fn group(&self) -> String {
        if self.kind == UpstreamType::Machine {
            format!("{}:{}/{}", self.upstream_host, self.upstream_port, self.name)
        } else {
            format!("{}:{}", self.upstream_host, self.upstream_port)
        }
    }

    /// The output `output`, when it is a machine's model with an address this process can call; `None` otherwise.
    pub fn read(output: &Value) -> Option<Self> {
        let kind = UpstreamType::of(output);
        if kind == UpstreamType::Cloud {
            return None;
        }
        let (id, name) = (Coerce::stripped(output.get("id")), Coerce::stripped(output.get("upstreamModel")));
        let upstream_port = u16::try_from(Coerce::int_or_zero(output.get("upstreamPort"))?).ok().filter(|port| *port > 0)?;
        let upstream_host = Coerce::stripped(output.get("upstreamHost"));
        // A cell answers whatever a request names: one model on its port. A machine's entry and an engine go by the name.
        if id.is_empty() || upstream_host.is_empty() || (name.is_empty() && kind != UpstreamType::Llama) {
            return None;
        }
        let ports = output.get("copyPorts").and_then(Value::as_array).into_iter().flatten();
        Some(Self {
            label: Coerce::text(output.get("name")),
            host: Coerce::text(output.get("hostId")),
            upstream_host,
            upstream_port,
            copy_ports: ports.filter_map(|port| Coerce::int(port).and_then(|port| u16::try_from(port).ok())).collect(),
            stopped: Coerce::truthy(output.get("stopped")),
            kind,
            id,
            name,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_machine_s_entry_has_a_queue_per_model_and_any_other_server_one() {
        let group = |raw: Value| MachineOutput::read(&raw).unwrap().group();
        assert_eq!(
            group(
                json!({"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 8092})
            ),
            "h:8092/m"
        );
        assert_eq!(
            group(
                json!({"id": "srv:1", "upstreamType": "llama", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 22001})
            ),
            "h:22001"
        );
        assert_eq!(
            group(
                json!({"id": "eng:1", "upstreamType": "engine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 11434})
            ),
            "h:11434"
        );
    }

    #[test]
    fn what_can_be_called_is_what_names_an_address() {
        let routers = json!([{"outputs": [
            {"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 8092},
            {"id": "c", "upstreamType": "cloud", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 443},
            {"id": "x"},
        ]}]);
        let outputs = RouterOutputs::read(Some(&routers));
        assert_eq!(outputs.callable().map(|output| output.id.as_str()).collect::<Vec<_>>(), ["mm:a"]);
    }

    #[test]
    fn the_first_output_of_an_id_answers_across_the_routers() {
        let routers = json!([{"outputs": [{"id": "a", "contextLength": 1}, "not an output"]}, {"outputs": [{"id": "a", "contextLength": 2}, {"id": "b"}]}, {}]);
        let outputs = RouterOutputs::read(Some(&routers));
        assert_eq!(outputs.get("a").unwrap().window, Some(1));
        assert!(outputs.get("b").is_some());
        assert!(outputs.get("c").is_none());
    }

    #[test]
    fn a_word_that_is_no_list_still_counts_as_said() {
        let of = |raw: Value| RouterOutput::read(&raw).unwrap();
        assert!(!of(json!({"id": "a"})).says_its_work);
        assert!(!of(json!({"id": "a", "jobs": []})).says_its_work);
        assert!(of(json!({"id": "a", "jobs": ["x"]})).says_its_work);
    }

    #[test]
    fn a_machine_s_model_needs_its_id_its_name_and_its_address() {
        let whole =
            json!({"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 1});
        assert!(MachineOutput::read(&whole).is_some());
        for field in ["id", "upstreamModel", "upstreamHost"] {
            let mut broken = whole.clone();
            broken[field] = json!("");
            assert!(MachineOutput::read(&broken).is_none(), "{field}");
        }
    }

    #[test]
    fn a_length_of_audio_is_a_whole_number_and_a_window_may_be_text() {
        let of = |raw: Value| RouterOutput::read(&raw).unwrap();
        assert_eq!(of(json!({"id": "a", "maxAudioMs": 0})).max_audio_ms, None);
        assert_eq!(of(json!({"id": "a", "maxAudioMs": 5})).max_audio_ms, Some(5));
        assert_eq!(of(json!({"id": "a", "maxAudioMs": "5"})).max_audio_ms, None);
        assert_eq!(of(json!({"id": "a", "maxAudioMs": true})).max_audio_ms, None);
        assert_eq!(of(json!({"id": "a", "contextLength": "5"})).window, Some(5));
        assert_eq!(of(json!({"id": "a", "contextLength": true})).window, None);
        assert_eq!(of(json!({"id": "a", "contextLength": 0})).window, None);
    }
}
