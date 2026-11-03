//! The machine's entry by OpenAI's API: one address for the models of this machine. A model is called by its name, not by the port of its cell. `GET /v1/models` lists the models of this machine, and a request names one in `model`: the scout hands
//! it to a running cell of that model and passes the answer back as it comes, a stream as a stream. The entry is open like the cells, no fleet token: everything it reaches is reachable on the cells' ports already, and it starts, stops and changes
//! nothing. What a model does is not said here: that is the controller's vocabulary, and a scout's guess at it would be a second copy of the rule.

pub mod body;
pub mod known;
pub mod machine_entry;
pub mod machine_models;
pub mod names;
pub mod request;
pub mod served;
