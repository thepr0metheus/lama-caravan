use super::*;

const NOW: f64 = 1000.0;
const OLD: &str = "aaaa1111";
const NEW: &str = "bbbb2222";
const HOST: &str = "box";

fn handing(tries: u32, in_flight: bool, settled: bool) -> Handing {
    Handing { release: NEW.to_string(), change: Change::Changed, tries, tried_at: NOW, in_flight, settled }
}

fn busy() -> Result<Value, NotTaken> {
    Err(NotTaken::Scout(AppError::with_status("box: not now: :22001 is loading. Nothing was changed", 409)))
}

fn decide(says: bool, same: Option<bool>, handing: Option<&Handing>, now: f64) -> Follow {
    ScoutFollow::decide(Some(NEW), says, OLD, || same, handing, now)
}

#[test]
fn a_scout_behind_is_handed_what_changed_and_only_that() {
    assert_eq!(decide(true, Some(false), None, NOW), Follow::Hand(Change::Changed));
    assert_eq!(decide(true, None, None, NOW), Follow::Hand(Change::Unknown), "a release it cannot be compared with is handed");
    assert_eq!(
        decide(true, Some(true), None, NOW),
        Follow::Same,
        "negative: the same program under another commit is not handed"
    );
}

#[test]
fn nothing_to_follow_reads_no_release_folder() {
    let unread = || -> Option<bool> { panic!("asked whether it is the same scout, with nothing to follow") };
    assert_eq!(ScoutFollow::decide(None, true, OLD, unread, None, NOW), Follow::Nothing, "no release");
    assert_eq!(ScoutFollow::decide(Some(NEW), true, NEW, unread, None, NOW), Follow::Nothing, "the release it runs already");
    assert_eq!(
        ScoutFollow::decide(Some(NEW), true, "", unread, None, NOW),
        Follow::Nothing,
        "a scout that does not say its release"
    );
    assert_eq!(
        ScoutFollow::decide(Some(NEW), false, OLD, unread, None, NOW),
        Follow::Nothing,
        "negative: a release silent on its scout"
    );
    let settled = handing(1, false, true);
    assert_eq!(
        ScoutFollow::decide(Some(NEW), true, OLD, unread, Some(&settled), NOW),
        Follow::Settled,
        "settled reads nothing either"
    );
}

#[test]
fn a_busy_scout_is_asked_again_later_and_not_for_ever() {
    assert_eq!(
        decide(true, Some(false), Some(&handing(1, true, false)), NOW + 10_000.0),
        Follow::Wait,
        "negative: one in flight is not doubled"
    );
    let said_not_now = handing(1, false, false);
    assert_eq!(
        decide(true, Some(false), Some(&said_not_now), NOW + ScoutFollow::RETRY_SEC - 1.0),
        Follow::Wait,
        "said not now: left alone"
    );
    assert_eq!(
        decide(true, Some(false), Some(&said_not_now), NOW + ScoutFollow::RETRY_SEC),
        Follow::Hand(Change::Changed),
        "asked again"
    );
    let tired = handing(ScoutFollow::TRIES, false, false);
    assert_eq!(decide(true, Some(false), Some(&tired), NOW + 10_000.0), Follow::Settled, "negative: not for ever");
    assert_eq!(
        decide(true, Some(false), Some(&handing(1, false, true)), NOW + 10_000.0),
        Follow::Settled,
        "taken or refused: settled in this run"
    );
}

#[test]
fn another_release_starts_afresh() {
    let other = Handing {
        release: "cccc3333".to_string(),
        change: Change::Changed,
        tries: ScoutFollow::TRIES,
        tried_at: NOW,
        in_flight: true,
        settled: true,
    };
    assert_eq!(decide(true, Some(false), Some(&other), NOW), Follow::Hand(Change::Changed));
}

#[test]
fn two_reports_at_once_hand_it_once_and_the_same_scout_is_said_once() {
    let follow = ScoutFollow::default();
    assert_eq!(follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW), Follow::Hand(Change::Changed));
    assert_eq!(
        follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + 1.0),
        Follow::Wait,
        "negative: the second report hands nothing"
    );
    let same = ScoutFollow::default();
    assert_eq!(same.step(HOST, Some(NEW), true, OLD, || Some(true), NOW), Follow::Same);
    assert_eq!(same.step(HOST, Some(NEW), true, OLD, || Some(true), NOW + 1.0), Follow::Settled, "said once, then quiet");
}

#[test]
fn what_the_scout_said_is_kept_and_a_busy_one_is_asked_again_up_to_the_last_try() {
    let follow = ScoutFollow::default();
    follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW);
    let words = follow.settled(HOST, NEW, &busy()).unwrap();
    assert!(words.contains("not now") && words.contains("try 1 of 15"), "{words}");
    assert_eq!(follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + 1.0), Follow::Wait);
    assert_eq!(
        follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + ScoutFollow::RETRY_SEC),
        Follow::Hand(Change::Changed)
    );
    let taken = follow.settled(HOST, NEW, &Ok(json!({"ok": true}))).unwrap();
    assert!(taken.contains("took bbbb2222: its scout restarts, and"), "{taken}");
    assert_eq!(follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + 10_000.0), Follow::Settled, "taken: nothing more");

    let tired = ScoutFollow::default();
    tired.lock().insert(HOST.to_string(), Handing { tries: ScoutFollow::TRIES, in_flight: true, ..handing(0, false, false) });
    let last = tired.settled(HOST, NEW, &busy()).unwrap();
    assert!(
        last.contains("did not take") && last.contains("Update the scout"),
        "negative: the last try is not followed by another: {last}"
    );
    let refused = ScoutFollow::default();
    refused.step(HOST, Some(NEW), true, OLD, || Some(false), NOW);
    let wrong = Err(NotTaken::Scout(AppError::with_status("box: what arrived is not what the controller named", 502)));
    assert!(refused.settled(HOST, NEW, &wrong).unwrap().contains("did not take"));
    assert_eq!(
        refused.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + 10_000.0),
        Follow::Settled,
        "negative: not asked again"
    );
    assert_eq!(
        ScoutFollow::default().settled(HOST, NEW, &busy()),
        None,
        "negative: a hand-out nobody began is no one's to settle"
    );
}

#[test]
fn a_scout_that_waits_for_its_requests_is_said_to_and_a_figure_it_does_not_give_is_not_made_up() {
    let follow = ScoutFollow::default();
    follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW);
    let waits = json!({"ok": true, "restarting": true, "waitsFor": {"words": ["2 requests through the machine's entry"], "requests": 2, "mostSec": 600.0}});
    let words = follow.settled(HOST, NEW, &Ok(waits)).unwrap();
    assert!(
        words.contains("took bbbb2222: its scout restarts once what passes through it is done (2 requests through the machine's entry), 600 s at the most"),
        "{words}"
    );
    assert_eq!(
        follow.step(HOST, Some(NEW), true, OLD, || Some(false), NOW + 10_000.0),
        Follow::Settled,
        "taken: not asked again while it waits"
    );
    let unsaid = ScoutFollow::restarts(&json!({"waitsFor": {"words": ["c22001 is loading"]}}));
    assert_eq!(
        unsaid, "its scout restarts once what passes through it is done (c22001 is loading), an unsaid time at the most",
        "negative"
    );
}

#[test]
fn the_menu_found_it_busy_and_the_reports_take_it_over_even_for_a_release_silent_on_its_scout() {
    let follow = ScoutFollow::default();
    assert!(follow.begin_by_hand(HOST, NEW, NOW));
    assert!(!follow.begin_by_hand(HOST, NEW, NOW + 1.0), "negative: a second press while one is under way");
    assert_eq!(
        follow.step(HOST, Some(NEW), false, OLD, || Some(false), NOW + 1.0),
        Follow::Wait,
        "negative: a report hands nothing meanwhile"
    );
    follow.settled(HOST, NEW, &busy()).unwrap();
    assert_eq!(follow.step(HOST, Some(NEW), false, OLD, || None, NOW + 1.0), Follow::Wait);
    assert_eq!(
        follow.step(HOST, Some(NEW), false, OLD, || None, NOW + ScoutFollow::RETRY_SEC),
        Follow::Hand(Change::ByHand),
        "asked again by the reports"
    );
    assert!(
        !follow.begin_by_hand(HOST, NEW, NOW + ScoutFollow::RETRY_SEC),
        "negative: a press while the reports' hand-out is in flight"
    );
    follow.settled(HOST, NEW, &Ok(json!({"ok": true}))).unwrap();
    assert!(follow.begin_by_hand(HOST, NEW, NOW + 10_000.0), "once it ended, the menu may ask again: a fresh round");
}

/// A controller that carries the release NEW, and the machine `box`, its scout at OLD answering the hand-out with `status` and `body`.
fn menu_rig(name: &str, status: &str, body: &[u8]) -> (crate::tests::TestFolder, std::sync::Arc<App>, crate::tests::StandIn) {
    let folder = crate::tests::TestFolder::new(&format!("scout-follow-{name}"));
    let app = crate::tests::TestApp::with_clock(&folder.path, &[], crate::tests::HandClock::at(1000));
    std::fs::write(folder.path.join("scout-bundle.tar.gz"), b"bundle").unwrap();
    std::fs::write(folder.path.join("scout-bundle.json"), format!(r#"{{"commit": "{NEW}", "sha256": "ff", "bytes": 6}}"#))
        .unwrap();
    let scout =
        crate::tests::StandIn::table(vec![("/api/scout/update".to_string(), status.to_string(), String::new(), body.to_vec())]);
    let address = scout.address().to_string();
    app.admin.saving(|doc| {
        doc.insert("topology".to_string(), json!({"hosts": {"box": {"id": "box", "agentUrl": address, "scoutCommit": OLD}}}));
    });
    (folder, app, scout)
}

#[test]
fn the_menu_hands_a_busy_scout_to_the_cycle_and_says_its_other_refusals_as_before() {
    let (_folder, app, scout) =
        menu_rig("busy", "409 Conflict", br#"{"error": "not now: :22001 is loading. Nothing was changed"}"#);
    let said = ScoutFollow::by_hand(&app, HOST).unwrap();
    assert_eq!(said["commit"], NEW);
    assert_eq!(said["restarting"], false, "nothing restarts now");
    assert!(said["waiting"]["words"].as_str().unwrap().contains("not now: :22001 is loading"), "{said}");
    assert_eq!(
        (said["waiting"]["retrySec"].as_f64(), said["waiting"]["tries"].as_u64()),
        (Some(ScoutFollow::RETRY_SEC), Some(15))
    );
    assert_eq!(scout.targets(), ["/api/scout/update"], "the scout was asked once");
    let at = |seconds: f64| app.scout_follow.step(HOST, Some(NEW), false, OLD, || None, 1000.0 + seconds);
    assert_eq!(at(1.0), Follow::Wait, "the reports took it over: left alone a while");
    assert_eq!(
        at(ScoutFollow::RETRY_SEC),
        Follow::Hand(Change::ByHand),
        "and asked again, though the release does not say its scout"
    );

    let (_folder, app, _scout) =
        menu_rig("wrong", "502 Bad Gateway", br#"{"error": "what arrived is not what the controller named"}"#);
    let refused = ScoutFollow::by_hand(&app, HOST).unwrap_err();
    assert_eq!(refused.status, 502, "negative: a refusal that is not 'not now' is the board's, as before");
    assert!(refused.message.contains("not what the controller named"), "{}", refused.message);
    assert_eq!(
        app.scout_follow.step(HOST, Some(NEW), false, OLD, || None, 5000.0),
        Follow::Settled,
        "negative: and not asked again"
    );

    let (_folder, app, _scout) =
        menu_rig("taken", "200 OK", format!(r#"{{"ok": true, "commit": "{NEW}", "restarting": true}}"#).as_bytes());
    assert_eq!(ScoutFollow::by_hand(&app, HOST).unwrap()["restarting"], true, "taken: the scout's answer as it came");
}
