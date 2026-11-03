//! The two places this machine keeps copies of models in, as one table: the model cache, and the folder for Strata's files. The owner, 2026-11-03: Strata needs a fast disk — while it answers it
//! reads its 29 GB table of n-grams at random, and through the controller or from an HDD it stalls — and a model it ran stays there after the stop, so that the next start does not write 68 GB to
//! the disk again ("so as not to wear the disk"), up to a size he chooses: 300 GB unless he says otherwise, and a model that would not fit is refused in words before a byte is copied. The code of
//! the cache keeps both; a row says only where they differ.

use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use crate::models::cache_off::CacheOff;
use crate::models::fetcher::{ModelFetcher, Progress};
use crate::models::files::SplitGguf;
use crate::models::folders::{ChosenFolder, Folders};
use crate::models::relocate::Relocation;
use crate::models::view::LibraryView;
use crate::models::view::reader::ControllerFiles;
use crate::state::ScoutState;
use os::clock::Clock;
use std::path::PathBuf;
use std::sync::Arc;

/// One place of copies.
#[derive(Debug)]
pub struct Shelf {
    /// Its word in the report: what moves.
    pub word: &'static str,
    /// Its name in a sentence.
    pub named: &'static str,
    /// What the operator can do when its disk is full, said after a refusal.
    pub when_full: &'static str,
    /// What the operator can do when a copy would take it over its budget, said after a refusal.
    pub when_over: &'static str,
    /// The key of its budget in `state.json`.
    pub budget_key: &'static str,
    /// The budget it keeps until the operator chooses one; `None`: the last models by count.
    pub budget_default: Option<i64>,
    /// The key of its log of starts in `state.json`.
    pub uses_key: &'static str,
    /// Whether the cache's switch takes it off: a machine that keeps no copies keeps none here.
    pub can_be_off: bool,
    /// Whether a model this machine has where the controller reads it is read there, with no copy.
    pub reads_in_place: bool,
    /// Whether a copy that would take it over its budget is refused before a byte is written. Otherwise the budget is what a trim keeps once a start ran.
    pub budget_bounds_copies: bool,
    /// The folder the board chose for it.
    choice: fn(&Folders) -> &ChosenFolder,
    /// Where it lies while the board chose none.
    fallback: fn(&Folders, &ScoutConfig) -> PathBuf,
}

impl Shelf {
    /// The model cache: the copies of every other cell, none while it is off.
    pub const CACHE: Self = Self {
        word: "cache",
        named: "the model cache",
        when_full: "Move the cache to a bigger folder, or turn it off.",
        when_over: "Raise the cache's budget on the machine's page (Model disk).",
        budget_key: "cacheBudgetBytes",
        budget_default: None,
        uses_key: "modelUse",
        can_be_off: true,
        reads_in_place: true,
        budget_bounds_copies: false,
        choice: |folders| &folders.cache,
        fallback: |_, config| ModelFetcher::own_cache_dir(config),
    };

    /// The folder for Strata's files: the copies of the cells whose runner needs a fast disk of the operator's choosing, and what they make from them. Never off and never read where the controller
    /// has a model — a library is a network share, an HDD at best — and of a size.
    pub const WORK: Self = Self {
        word: "work",
        named: "the folder for Strata's files",
        when_full: "Choose a bigger disk for it on the machine's page (Model disk → Strata files), or stop a Strata cell.",
        when_over: "Raise its limit on the machine's page (Model disk → Strata files), or stop a Strata cell.",
        budget_key: "workBudgetBytes",
        budget_default: Some(300 << 30),
        uses_key: "workModelUse",
        can_be_off: false,
        reads_in_place: false,
        budget_bounds_copies: true,
        choice: |folders| &folders.work,
        fallback: Self::unchosen_work,
    };

    /// Where it lies now.
    pub fn dir(&self, folders: &Folders, config: &ScoutConfig) -> PathBuf {
        (self.choice)(folders).value().unwrap_or_else(|| (self.fallback)(folders, config))
    }

    /// Whether it lies in a folder the board chose.
    pub fn chosen(&self, folders: &Folders) -> bool {
        (self.choice)(folders).value().is_some()
    }

    /// The folder for Strata's files while none is chosen: `.strata` in the cache's folder. A start that needs it is refused then, so that nothing is written there; a folder of its own keeps its
    /// record and its cells' files apart from the cache's.
    fn unchosen_work(folders: &Folders, config: &ScoutConfig) -> PathBuf {
        Self::CACHE.dir(folders, config).join(".strata")
    }
}

/// What the two shelves of a machine share: its settings, where a download's progress goes, the folders the board chose, the cache's switch, the view of the library (one mount), the one move at
/// a time, the clocks, HTTP and the rule of split files.
pub struct ShelfParts {
    /// The settings.
    pub config: Arc<ScoutConfig>,
    /// Where a download's progress goes.
    pub report: Progress,
    /// The folders the board chose.
    pub folders: Arc<Folders>,
    /// The cache's switch.
    pub off: Arc<CacheOff>,
    /// A model with no copy here, as a file a program can read.
    pub view: Arc<LibraryView>,
    /// The moves of either shelf's folder.
    pub relocation: Arc<Relocation>,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    /// How the scout asks over HTTP.
    pub http: Arc<HttpClient>,
    /// The rule of split files.
    pub splits: Arc<SplitGguf>,
}

impl ShelfParts {
    /// The parts kept in this state.
    pub fn new(
        config: Arc<ScoutConfig>,
        report: Progress,
        state: &Arc<ScoutState>,
        clock: Arc<dyn Clock>,
        http: Arc<HttpClient>,
        splits: Arc<SplitGguf>,
    ) -> Self {
        let off = Arc::new(CacheOff::new(Arc::clone(state)));
        let files = ControllerFiles::new(Arc::clone(&config), Arc::clone(&http));
        Self {
            folders: Arc::new(Folders::new(state)),
            view: Arc::new(LibraryView::new(off.view_folder(), files)),
            off,
            relocation: Arc::default(),
            config,
            report,
            clock,
            http,
            splits,
        }
    }

    /// The same, with this word on whether the machine can show a model through the controller: a test's.
    #[cfg(test)]
    pub fn with_view_word(mut self, can: fn() -> bool) -> Self {
        if let Some(view) = Arc::get_mut(&mut self.view) {
            view.take_word(can);
        }
        self
    }
}
