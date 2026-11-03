//! How a cell's own words are read. One vocabulary for the words a cell writes, whoever carries them to the board.

/// The vocabulary.
pub struct CellWords;

type Needles = (&'static str, &'static [&'static str]);

impl CellWords {
    const FAILURE: [Needles; 4] = [
        ("exec", &["status=203", "203/exec", "failed to locate executable", "permission denied"]),
        (
            "oom",
            &[
                "out of memory",
                "cudamalloc",
                "failed to allocate",
                "unable to allocate",
                "erroroutofdevicememory",
                "not enough memory",
                "insufficient memory",
            ],
        ),
        (
            "model",
            &[
                "gguf_init_from_file",
                "error loading model",
                "failed to load model",
                "no such file or directory",
                "model not found",
                "mmproj not found",
                "spec draft not found",
                "library not mounted",
            ],
        ),
        ("port", &["address already in use", "couldn't bind", "failed to bind"]),
    ];
    const PROGRESS: [Needles; 7] = [
        ("starting API", &["starting vllm api server", "uvicorn running", "application startup complete"]),
        ("capturing CUDA graphs", &["capturing cuda graph", "cudagraph", "graph capturing finished"]),
        ("compiling kernels", &["torch.compile", "dynamo bytecode", "compiling", "inductor"]),
        ("loading weights", &["loading safetensors", "model loading took", "loading weights", "load_tensors", "loading model"]),
        ("downloading model", &["downloading", "fetching ", "%|"]),
        ("provisioning venv", &["provisioning vllm venv"]),
        ("warming up", &["warming up", "kv cache", "encoder cache"]),
    ];
    const CRASH: [Needles; 4] = [
        ("gpu-hang", &["the launch timed out", "unspecified launch failure", "gpu is probably locked", "xid"]),
        ("gpu-oom", &["out of memory", "cudamalloc", "erroroutofdevicememory"]),
        ("assert", &["ggml_assert", "ggml_abort", "assertion"]),
        ("killed", &["killed", "out of memory: killed process", "oom-killer", "sigkill"]),
    ];

    fn first_named(table: &[Needles], text: &str) -> Option<&'static str> {
        let low = text.to_lowercase();
        table.iter().find(|(_, needles)| needles.iter().any(|needle| low.contains(needle))).map(|(name, _)| *name)
    }

    /// exec, oom, model, port; or "crash" when no word says which.
    pub fn failure_kind(text: &str) -> &'static str {
        Self::first_named(&Self::FAILURE, text).unwrap_or("crash")
    }

    /// The latest stage its lines name; empty for none.
    pub fn progress_note(text: &str) -> &'static str {
        text.lines().rev().find_map(|line| Self::first_named(&Self::PROGRESS, line)).unwrap_or("")
    }

    /// gpu-hang, gpu-oom, assert, killed; or "crash".
    pub fn crash_kind(text: &str) -> &'static str {
        Self::first_named(&Self::CRASH, text).unwrap_or("crash")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cell_s_words_name_what_happened() {
        assert_eq!(CellWords::failure_kind("Failed to Load Model x"), "model");
        assert_eq!(CellWords::failure_kind("Address already in use"), "port");
        assert_eq!(CellWords::failure_kind("nothing known"), "crash");
        assert_eq!(CellWords::crash_kind("GGML_ASSERT failed"), "assert");
        assert_eq!(CellWords::crash_kind("x"), "crash");
        assert_eq!(CellWords::progress_note("Loading weights\nwarming up\nnothing"), "warming up");
        assert_eq!(CellWords::progress_note(""), "");
    }
}
