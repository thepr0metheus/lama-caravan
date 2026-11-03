//! A pool that was edited is decided again at once, with no request to ask for it.
//!
//! Which row a pool serves with is the proxy's word, and the board's "Serving now" says that word and nothing else. An edit sends no request:
//! a row carried to the top of its pool changed what the next request will meet and not what the card said. Here the proxy looks at what it
//! reads and, when a pool's reading is not the one it last decided by, decides that pool again, as a request would. What this leaves alone:
//! the first look decides nothing, a decision sends nothing to a provider but the question of its limits, and a pool nothing changed keeps
//! what the last request made of it.

use crate::log::Log;
use crate::proxy::Proxy;
use files::Settings;
use rules::{Pool, RowWork};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

/// What the pools looked like when they were last decided by.
#[derive(Default)]
pub struct PoolWatch {
    /// The reading looked at last: the same one has nothing new to say.
    settings: Option<Arc<Settings>>,
    /// Each pool's reading as text; `None` until the first look.
    seen: Option<BTreeMap<String, String>>,
}

impl PoolWatch {
    /// How often it looks. A look is a few stats unless a file changed.
    const TURN: Duration = Duration::from_secs(1);

    /// The ids of the pools the look at `settings` decided again.
    pub fn sweep(&mut self, proxy: &Proxy, settings: &Arc<Settings>) -> Vec<String> {
        if self.settings.as_ref().is_some_and(|seen| Arc::ptr_eq(seen, settings)) {
            return Vec::new();
        }
        self.settings = Some(Arc::clone(settings));
        let pools = settings.models.file_pools();
        let readings: BTreeMap<String, String> =
            pools.iter().map(|pool| (pool.id.clone(), Self::reading(settings, pool))).collect();
        let before = self.seen.replace(readings.clone());
        let Some(before) = before else {
            return Vec::new();
        };
        let changed = pools.iter().filter(|pool| before.get(&pool.id) != readings.get(&pool.id));
        changed.map(|pool| Self::decided(proxy, settings, pool)).collect()
    }

    fn decided(proxy: &Proxy, settings: &Settings, pool: &Pool) -> String {
        proxy.choose_row(settings, pool, b"", "", &BTreeSet::new());
        pool.id.clone()
    }

    /// All a pool's choice is made by that does not change by itself: its rows, what each account is, and the levels and schedules of the file.
    fn reading(settings: &Settings, pool: &Pool) -> String {
        let models = &settings.models;
        let accounts: Vec<_> = pool
            .rows
            .iter()
            .filter_map(|row| match &row.work {
                RowWork::Account { account, model } => {
                    let provider = models.provider(account);
                    let signed_in =
                        provider.as_ref().is_some_and(|provider| models.has_credential(&provider.credential_account_id));
                    let listed =
                        provider.as_ref().map(|provider| models.catalogue().lists(&provider.credential_account_id, model));
                    Some((provider, signed_in, listed))
                }
                RowWork::Output(_) | RowWork::Open => None,
            })
            .collect();
        format!("{pool:?} {accounts:?} {:?} {:?}", models.levels(), models.schedules())
    }

    /// Looks every turn until a new version comes: the state file is the new one's from then.
    fn run(mut self, proxy: &Proxy) {
        while !proxy.drain.is_on() {
            if !self.sweep(proxy, &proxy.settings.current()).is_empty() {
                proxy.board.touch();
            }
            std::thread::sleep(Self::TURN);
        }
    }

    /// The watch, on a thread of its own: a decision may wait for a provider's answer on an account's limits.
    pub fn start(proxy: &Arc<Proxy>) {
        let proxy = Arc::clone(proxy);
        let watch = std::thread::Builder::new().name("pool-watch".into()).spawn(move || Self::default().run(&proxy));
        if let Err(error) = watch {
            Log::line(&format!("caravan-proxy: no thread for the pool watch: {error}"));
        }
    }
}
