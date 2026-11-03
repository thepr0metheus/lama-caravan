//! A process that takes its time to go down, as a real one does.

#![allow(clippy::unwrap_used, reason = "a test may stop where it found something wrong")]

use super::*;
use crate::commands::SystemCommands;
use crate::tests::TestFolder;
use os::clock::SystemClock;
use serde_json::{Map, json};
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

fn process() -> CellProcess {
    CellProcess::new(ProcessParts {
        clock: Arc::new(SystemClock::new()),
        scope: Arc::new(MemoryScope::new(Arc::new(SystemCommands), false)),
        patterns: Arc::new(LogPatterns::new().unwrap()),
        total_memory_mib: None,
        home: "/home/scout".to_string(),
    })
}

#[test]
fn a_process_on_its_way_down_is_read_at_once_and_runs_until_it_is_gone_and_a_start_waits_for_that() {
    let folder = TestFolder::new("process-stop");
    let ready = folder.path.join("ready");
    let process = Arc::new(process());
    // It leaves a second after it is told to, and says when it can hear that.
    let line = format!("sleep 30 & sleeper=$!; trap 'kill $sleeper; sleep 1; exit 0' TERM; touch '{}'; wait", ready.display());
    let started = process.start_command(&line, Map::new(), None, &Map::new(), 0.0);
    assert_eq!(started.get("ok"), Some(&json!(true)), "{started}");
    let limit = Instant::now() + Duration::from_secs(20);
    while !ready.exists() {
        assert!(Instant::now() < limit, "it never said it can hear");
        std::thread::sleep(Duration::from_millis(20));
    }
    let stopping = {
        let process = Arc::clone(&process);
        std::thread::spawn(move || process.stop())
    };
    std::thread::sleep(Duration::from_millis(300));
    assert_eq!(
        process.status().get("running"),
        Some(&json!(true)),
        "it still runs, and whoever asks hears that while the stop waits"
    );
    assert!(!stopping.is_finished(), "asked and answered while the stop went on");
    let again = process.start_command("sleep 30", Map::new(), None, &Map::new(), 0.0);
    assert_eq!(again.get("ok"), Some(&json!(true)), "a start waits for the stop before it: {again}");
    assert_eq!(stopping.join().unwrap().get("ok"), Some(&json!(true)));
    assert_eq!(process.status().get("running"), Some(&json!(true)), "the new one");
    assert_eq!(process.stop().get("ok"), Some(&json!(true)));
    assert_eq!(process.status().get("running"), Some(&json!(false)));
}

#[test]
fn a_cell_is_this_scout_s_when_it_says_so_or_says_nothing_of_whose() {
    let folder = TestFolder::new("process-home");
    let write = |pid: i64, environment: &str| {
        std::fs::create_dir_all(folder.path.join(pid.to_string())).unwrap();
        std::fs::write(folder.path.join(pid.to_string()).join("environ"), environment.replace(' ', "\0")).unwrap();
    };
    write(10, "A=1 CARAVAN_SCOUT_CELL=22003 CARAVAN_SCOUT_HOME=/home/scout Z=2");
    write(11, "CARAVAN_SCOUT_CELL=22004");
    write(12, "CARAVAN_SCOUT_CELL=22005 CARAVAN_SCOUT_HOME=/tmp/another");
    write(13, "CARAVAN_SCOUT_HOME=/home/scout");
    let processes = HostProcesses::new(folder.path.clone(), Arc::new(SystemCommands)).of_scout(Path::new("/home/scout"));
    assert_eq!(processes.port_of(10), 22003, "started by this scout");
    assert_eq!(processes.port_of(11), 22004, "started before scouts said whose");
    assert_eq!(processes.port_of(12), 0, "another scout's: its cell is its own");
    assert_eq!(processes.port_of(13), 0, "no cell");
    assert_eq!(processes.owned(12), Some(true), "and it is still a scout's, for what asks only that");
}

#[test]
fn a_cell_s_scope_is_a_scope_made_for_a_command_alone_and_holds_what_stands_in_it() {
    let folder = TestFolder::new("process-scope");
    let (procs, groups) = (folder.path.join("proc"), folder.path.join("groups"));
    let stands_in = |pid: i64, group: &str| {
        std::fs::create_dir_all(procs.join(pid.to_string())).unwrap();
        std::fs::write(procs.join(pid.to_string()).join("cgroup"), format!("0::{group}\n")).unwrap();
    };
    let app = "/user.slice/user-1000.slice/user@1000.service/app.slice";
    stands_in(10, &format!("{app}/run-r80aee.scope"));
    stands_in(11, &format!("{app}/caravan-scout.service"));
    stands_in(12, "/user.slice/user-1000.slice/session-3.scope");
    stands_in(13, &format!("{app}/run-rmine.scope"));
    stands_in(i64::from(std::process::id()), &format!("{app}/run-rmine.scope"));
    let group = groups.join(format!("{}/run-r80aee.scope", app.trim_start_matches('/')));
    std::fs::create_dir_all(&group).unwrap();
    std::fs::write(group.join("cgroup.procs"), "4094950\n4094951\n").unwrap();
    let processes = HostProcesses::new(procs, Arc::new(SystemCommands)).groups_under(groups);
    assert_eq!(
        processes.scope_of(10).unwrap().pids(),
        [4094950, 4094951],
        "whoever stands there, whatever it did to its environment"
    );
    assert!(processes.scope_of(11).is_none(), "a service's group: a cell with no limits stands in the scout's");
    assert!(processes.scope_of(12).is_none(), "a login's: nothing of a session is a cell's to lose");
    assert!(processes.scope_of(13).is_none(), "the scope the scout itself stands in");
    assert!(processes.scope_of(99).is_none(), "no such process");
    std::fs::remove_file(group.join("cgroup.procs")).unwrap();
    assert_eq!(processes.scope_of(10).unwrap().pids(), Vec::<i64>::new(), "a scope gone with its last process holds nothing");
}
