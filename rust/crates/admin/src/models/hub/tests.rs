//! What the hub says, by the values it was once caught saying; and a stand-in hub's words for the other modules' tests.

use super::*;
use crate::app::App;
use crate::tests::StandIn;
use crate::web::{Exchange, Routes};
use rules::AppError;
use std::io::{BufReader, Read};
use std::net::{Shutdown, TcpListener, TcpStream};
use wire::{Headers, RequestHead};

const SHA256: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
const SHA1: &str = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad";
const REAL_HUB: &str = "https://huggingface.co";
const API: &str = "https://huggingface.co/api/models/org/Repo/tree/main";
const TREE: &str = "https://huggingface.co/api/models/org/Repo/tree/main?recursive=true&expand=true";

/// A row of a stand-in's table: `(path, status, fields, body)`.
pub(crate) type Row = (String, String, String, Vec<u8>);

/// What a stand-in hub says, in the hub's own shapes.
pub(crate) struct TestHub;

impl TestHub {
    /// 64 asterisks: what the hub puts where an LFS hash stands, for a gated repository whose terms the token has not accepted.
    pub(crate) fn mask() -> String {
        "*".repeat(64)
    }

    /// An ordinary file of a tree: its git blob id in `oid`.
    pub(crate) fn plain(path: &str, size: i64, git: &str) -> Value {
        json!({"type": "file", "path": path, "size": size, "oid": git, "securityFileStatus": {"status": "unscanned"},
               "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-01T00:00:00.000Z"}})
    }

    /// An LFS file of a tree: its own `oid` names the pointer, and `lfs.oid` the content.
    pub(crate) fn lfs(path: &str, size: i64, sha: &str) -> Value {
        json!({"type": "file", "path": path, "size": size, "oid": "e".repeat(40), "xetHash": "x".repeat(64),
               "lfs": {"oid": sha, "size": size, "pointerSize": 135}, "securityFileStatus": {"status": "unscanned"},
               "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-02T00:00:00.000Z"}})
    }

    /// A folder's entry in a tree.
    pub(crate) fn folder(path: &str) -> Value {
        json!({"type": "directory", "path": path, "size": 0, "oid": "f".repeat(40)})
    }

    /// A row that answers `doc` as JSON.
    pub(crate) fn json(path: &str, doc: &Value) -> Row {
        (path.to_string(), "200 OK".to_string(), String::new(), doc.to_string().into_bytes())
    }

    /// The row of a repository's tree: one page, with no next.
    pub(crate) fn tree(repo: &str, entries: Vec<Value>) -> Row {
        Self::json(&format!("/api/models/{repo}/tree/main"), &Value::Array(entries))
    }

    /// The row of a repository's config.json, read where the hub serves it: no redirect.
    pub(crate) fn config(repo: &str, doc: &Value) -> Row {
        Self::json(&format!("/{repo}/resolve/main/config.json"), doc)
    }

    /// A row that sends the asker to `to`, relative to the hub, as the hub does for a renamed repository and an ordinary file.
    pub(crate) fn moved(path: &str, to: &str) -> Row {
        (path.to_string(), "307 Temporary Redirect".to_string(), format!("Location: {to}\r\n"), b"Temporary Redirect".to_vec())
    }

    /// A row that refuses.
    pub(crate) fn refused(path: &str, status: &str) -> Row {
        (path.to_string(), status.to_string(), String::new(), b"{\"error\": \"refused\"}".to_vec())
    }
}

/// A route of a topic's table, called as the server calls it, past the server's guard: `(status, what it answered)`.
pub(crate) struct RouteCall;

impl RouteCall {
    /// A GET.
    pub(crate) fn get(app: &App, routes: &Routes, target: &str) -> (u16, Value) {
        let path = target.split('?').next().unwrap();
        let route = routes.get.iter().find(|row| row.0 == path).unwrap().1;
        Self::over("GET", target, |exchange| route(app, exchange))
    }

    /// A POST with this body.
    pub(crate) fn post(app: &App, routes: &Routes, target: &str, body: Value) -> (u16, Value) {
        let route = routes.post.iter().find(|row| row.0 == target).unwrap().1;
        Self::over("POST", target, |exchange| route(app, exchange, body))
    }

    /// A GET of a page: `(status, the answer's body as text)`.
    pub(crate) fn page(app: &App, routes: &Routes, target: &str) -> (u16, String) {
        let route = routes.get.iter().find(|row| row.0 == target).unwrap().1;
        Self::raw("GET", target, |exchange| route(app, exchange))
    }

    fn over(method: &str, target: &str, work: impl FnOnce(&mut Exchange<'_>) -> Result<(), AppError>) -> (u16, Value) {
        let (status, body) = Self::raw(method, target, work);
        (status, serde_json::from_str(&body).unwrap())
    }

    fn raw(method: &str, target: &str, work: impl FnOnce(&mut Exchange<'_>) -> Result<(), AppError>) -> (u16, String) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (server, _) = listener.accept().unwrap();
        let reader = std::thread::spawn(move || {
            let mut raw = Vec::new();
            client.read_to_end(&mut raw).unwrap();
            raw
        });
        let mut source = BufReader::new(server.try_clone().unwrap());
        let head = RequestHead { method: method.to_string(), target: target.to_string(), headers: Headers::new() };
        let mut exchange = Exchange::new(head, &mut source, &server, "127.0.0.1".to_string(), 0, "test");
        if let Err(error) = work(&mut exchange) {
            exchange.send_json(&json!({"error": error.message}), error.status);
        }
        server.shutdown(Shutdown::Both).unwrap();
        let raw = String::from_utf8(reader.join().unwrap()).unwrap();
        let (head, body) = raw.split_once("\r\n\r\n").unwrap();
        (head.split_whitespace().nth(1).unwrap().parse().unwrap(), body.to_string())
    }
}

/// A hash as a tree's entry reads: its kind, and its value when it has one.
fn read(item: &Value) -> (&'static str, String) {
    let hash = HubHash::from_tree_item(item);
    (hash.kind(), hash.value().unwrap_or_default().to_string())
}

fn pointer_id() -> String {
    format!("0bb57c08c47f{}", "a".repeat(28))
}

#[test]
fn an_lfs_entry_reads_its_sha256_from_the_lfs_record_and_not_from_its_own_oid() {
    let entry = json!({"oid": pointer_id(), "lfs": {"oid": SHA256, "size": 9, "pointerSize": 135}});
    assert_eq!(read(&entry), ("sha256", SHA256.to_string()));
}

#[test]
fn an_upper_case_sha256_is_the_same_hash_in_lower_case() {
    let entry = json!({"oid": pointer_id(), "lfs": {"oid": SHA256.to_uppercase(), "size": 9}});
    assert_eq!(read(&entry), ("sha256", SHA256.to_string()));
}

#[test]
fn an_ordinary_entry_reads_its_git_blob_id() {
    assert_eq!(read(&json!({"oid": SHA1})), ("git-sha1", SHA1.to_string()));
}

#[test]
fn a_masked_oid_reads_as_hidden_and_never_as_a_hash() {
    let mask = TestHub::mask();
    let entry = json!({"oid": pointer_id(), "lfs": {"oid": mask, "size": 4_877_470_304_i64, "pointerSize": 135}});
    assert_eq!(read(&entry), ("hidden", String::new()));
    assert_eq!(read(&json!({"oid": SHA1, "lfs": {"oid": mask}})).0, "hidden", "a pointer's blob id is not the content's hash");
    assert_eq!(read(&json!({"lfs": {"oid": "*"}})).0, "hidden", "asterisks and nothing else are a mask, however many");
}

#[test]
fn an_lfs_entry_with_no_hash_of_its_own_is_none_whatever_its_own_oid_says() {
    for lfs in [json!({"size": 9}), json!({"oid": "", "size": 9}), json!({"oid": null}), json!({})] {
        assert_eq!(read(&json!({"oid": SHA1, "lfs": lfs})), ("none", String::new()), "{lfs}");
    }
}

#[test]
fn junk_where_an_lfs_hash_stands_is_none_and_not_hidden() {
    for oid in ["unavailable", &SHA256[..63], "***x", "z".repeat(64).as_str()] {
        assert_eq!(read(&json!({"oid": SHA1, "lfs": {"oid": oid}})), ("none", String::new()), "{oid}");
    }
}

#[test]
fn an_ordinary_entry_whose_oid_is_no_git_id_is_none() {
    for item in [
        json!({"oid": SHA256}),
        json!({"oid": "*".repeat(40)}),
        json!({"oid": ""}),
        json!({"oid": null, "lfs": {"oid": null}}),
        json!({}),
        json!({"oid": &SHA1[..39]}),
        json!({"oid": "g".repeat(40)}),
    ] {
        assert_eq!(read(&item), ("none", String::new()), "{item}");
    }
}

#[test]
fn the_listings_words_keep_oid_for_the_sha256_alone() {
    let words = |hash: HubHash| Value::Object(hash.fields());
    assert_eq!(words(HubHash::Sha256(SHA256.to_string())), json!({"oid": SHA256, "gitOid": "", "hashHidden": false}));
    assert_eq!(words(HubHash::GitSha1(SHA1.to_string())), json!({"oid": "", "gitOid": SHA1, "hashHidden": false}));
    assert_eq!(words(HubHash::Hidden), json!({"oid": "", "gitOid": "", "hashHidden": true}));
    assert_eq!(words(HubHash::None), json!({"oid": "", "gitOid": "", "hashHidden": false}));
}

#[test]
fn what_a_listing_carries_reads_back_as_the_same_hash() {
    for hash in [HubHash::Sha256(SHA256.to_string()), HubHash::GitSha1(SHA1.to_string()), HubHash::Hidden, HubHash::None] {
        assert_eq!(HubHash::from_entry(&Value::Object(hash.fields())), hash);
    }
}

#[test]
fn a_mask_that_reached_oid_can_never_be_compared() {
    let mask = TestHub::mask();
    assert_eq!(HubHash::from_entry(&json!({"oid": mask})), HubHash::None);
    assert_eq!(HubHash::from_entry(&json!({"oid": mask, "hashHidden": true})), HubHash::Hidden, "and the flag still says why");
}

#[test]
fn a_usable_sha256_wins_over_the_rest_of_an_entry() {
    let entry = json!({"oid": SHA256, "gitOid": SHA1, "hashHidden": true});
    assert_eq!(HubHash::from_entry(&entry), HubHash::Sha256(SHA256.to_string()));
    assert_eq!(HubHash::from_entry(&json!({"oid": "", "gitOid": SHA1, "hashHidden": true})), HubHash::GitSha1(SHA1.to_string()));
}

#[test]
fn hash_hidden_is_a_flag_that_is_true_or_is_not() {
    for said in [json!("yes"), json!(1), json!("true"), json!(false), json!(null)] {
        assert_eq!(HubHash::from_entry(&json!({"oid": "", "hashHidden": said})), HubHash::None, "{said}");
    }
    assert_eq!(HubHash::from_entry(&json!({})), HubHash::None, "an old-shaped entry");
}

#[test]
fn only_the_two_kinds_with_a_value_can_be_held_against_a_file() {
    assert_eq!(HubHash::Sha256(SHA256.to_string()).value(), Some(SHA256));
    assert_eq!(HubHash::GitSha1(SHA1.to_string()).value(), Some(SHA1));
    assert_eq!(HubHash::Hidden.value(), None);
    assert_eq!(HubHash::None.value(), None);
}

fn link(url: &str) -> String {
    format!("<{url}>; rel=\"next\"")
}

fn pages() -> HubPages {
    HubPages::new().unwrap()
}

#[test]
fn a_page_asks_for_the_largest_size_unless_it_names_one() {
    assert_eq!(HubPages::sized(TREE), format!("{TREE}&limit=100"));
    assert_eq!(HubPages::sized(&format!("{TREE}&limit=20")), format!("{TREE}&limit=20"));
    assert_eq!(HubPages::sized(API), format!("{API}?limit=100"), "an address with no query gets one");
    assert_eq!(HubPages::sized(&format!("{API}?limit")), format!("{API}?limit"), "a limit with no value is still named");
    assert_eq!(
        HubPages::sized(&format!("{API}?nolimit=1")),
        format!("{API}?nolimit=1&limit=100"),
        "a word that ends like it is not it"
    );
}

#[test]
fn the_next_page_is_the_address_of_rel_next_as_sent() {
    let first = format!("{TREE}&limit=50&cursor=ZXlK%3D");
    assert_eq!(pages().next_url(REAL_HUB, &link(&first)), Ok(first.clone()));
    assert_eq!(pages().next_url(REAL_HUB, &format!("<{first}>; rel=next")), Ok(first.clone()), "the quotes are not required");
    assert_eq!(pages().next_url(REAL_HUB, &format!("<{first}>; REL=\"NEXT\"")), Ok(first), "nor is the case");
    assert_eq!(pages().next_url(REAL_HUB, ""), Ok(String::new()), "no field: no next page");
}

#[test]
fn only_next_is_followed_and_not_a_relation_that_starts_like_it() {
    let first = format!("{TREE}&limit=50&cursor=b");
    assert_eq!(pages().next_url(REAL_HUB, &format!("<{TREE}&cursor=a>; rel=\"prev\"")), Ok(String::new()));
    assert_eq!(pages().next_url(REAL_HUB, &format!("<{first}>; rel=\"nextish\"")), Ok(String::new()));
    assert_eq!(pages().next_url(REAL_HUB, &format!("<{first}>; rel=\"next-to\"")), Ok(String::new()));
}

#[test]
fn two_links_in_one_field_give_the_next_among_them() {
    let first = format!("{TREE}&limit=50&cursor=b");
    let field = format!("<{TREE}&cursor=a>; rel=\"prev\", {}", link(&first));
    assert_eq!(pages().next_url(REAL_HUB, &field), Ok(first.clone()));
    let turned = format!("{}, <{TREE}&cursor=a>; rel=\"prev\"", link(&first));
    assert_eq!(pages().next_url(REAL_HUB, &turned), Ok(first), "whichever comes first");
}

#[test]
fn a_next_page_outside_the_hubs_api_is_refused_for_the_token_would_go_along() {
    for bad in [
        "https://evil.example/api/models/x/tree/main?cursor=1",
        "http://huggingface.co/api/models/x/tree/main?cursor=1",
        "https://huggingface.co/not-the-api/x?cursor=1",
        "https://huggingface.co.evil.example/api/x?cursor=1",
    ] {
        let said = pages().next_url(REAL_HUB, &link(bad)).unwrap_err();
        assert!(
            said.contains("outside its API") && said.contains("evil.example") == bad.contains("evil.example"),
            "{bad}: {said}"
        );
    }
}

#[test]
fn a_list_of_three_pages_is_one_list_in_the_hubs_order() {
    let (first, second, third) =
        (format!("{TREE}&limit=100"), format!("{TREE}&limit=100&cursor=2"), format!("{TREE}&limit=100&cursor=3"));
    let mut asked = Vec::new();
    let list = pages().read(REAL_HUB, TREE, |page| {
        asked.push(page.to_string());
        Ok(match asked.len() {
            1 => (json!(["a", "b"]), link(&second)),
            2 => (json!(["c"]), link(&third)),
            _ => (json!(["d", "e"]), String::new()),
        })
    });
    assert_eq!(list, Ok(json!(["a", "b", "c", "d", "e"])));
    assert_eq!(asked, [first, second.clone(), third.clone()], "each page once, the first with the page's size");
}

#[test]
fn a_list_of_one_page_is_one_request_and_an_empty_list_is_an_empty_list() {
    let mut asked = 0;
    let list = pages().read(REAL_HUB, TREE, |_| {
        asked += 1;
        Ok((json!([]), String::new()))
    });
    assert_eq!((list, asked), (Ok(json!([])), 1));
}

#[test]
fn more_pages_than_the_limit_is_an_error_after_fifty_requests_and_no_short_list() {
    let mut asked = 0;
    let said = pages().read(REAL_HUB, TREE, |_| {
        asked += 1;
        Ok((json!(["x"]), link(&format!("{TREE}&cursor={asked}"))))
    });
    assert!(said.as_ref().is_err_and(|words| words.contains("not read to the end")), "{said:?}");
    assert_eq!(asked, 50);
}

#[test]
fn a_later_page_that_fails_is_the_error_and_not_the_pages_before_it() {
    let said = pages().read(REAL_HUB, TREE, |page| {
        if page.contains("cursor") {
            Err("HTTP Error 404: Not Found".to_string())
        } else {
            Ok((json!(["a"]), link(&format!("{TREE}&cursor=2"))))
        }
    });
    assert_eq!(said, Err("HTTP Error 404: Not Found".to_string()));
}

#[test]
fn a_later_page_that_is_no_list_is_an_error_and_a_first_one_is_the_answer() {
    let said = pages().read(REAL_HUB, TREE, |page| {
        if page.contains("cursor") {
            Ok((json!({"error": "x"}), String::new()))
        } else {
            Ok((json!(["a"]), link(&format!("{TREE}&cursor=2"))))
        }
    });
    assert!(said.as_ref().is_err_and(|words| words.contains("not a list")), "{said:?}");
    let first = pages().read(REAL_HUB, TREE, |_| Ok((json!({"error": "Repository not found"}), String::new())));
    assert_eq!(first, Ok(json!({"error": "Repository not found"})), "the caller reads its error");
}

#[test]
fn a_next_page_of_another_host_ends_the_read_with_an_error() {
    let said = pages().read(REAL_HUB, TREE, |_| Ok((json!(["a"]), link("https://evil.example/api/x"))));
    assert!(said.as_ref().is_err_and(|words| words.contains("outside its API")), "{said:?}");
}

#[test]
fn a_hub_told_by_its_address_keeps_its_next_pages_at_that_address() {
    let hub = "http://127.0.0.1:9";
    assert_eq!(
        pages().next_url(hub, &link("http://127.0.0.1:9/api/x?cursor=1")),
        Ok("http://127.0.0.1:9/api/x?cursor=1".to_string())
    );
    assert!(
        pages().next_url(hub, &link("https://huggingface.co/api/x?cursor=1")).is_err(),
        "the real one is another host for it"
    );
    assert!(pages().next_url(hub, &link("http://127.0.0.1:90/api/x")).is_err(), "a port that only begins like its own");
}

#[test]
fn the_hubs_fields_say_who_asks_and_the_token_only_when_there_is_one() {
    assert_eq!(HubAccess::fields(""), [("User-Agent", "lama-caravan/1.0".to_string())]);
    assert_eq!(
        HubAccess::fields("t"),
        [("User-Agent", "lama-caravan/1.0".to_string()), ("Authorization", "Bearer t".to_string())]
    );
}

#[test]
fn a_wall_is_401_and_403_and_nothing_a_retry_could_change() {
    let status = |code| HttpError::Status(code, String::new());
    assert!(HubAccess::is_wall(&status(401)) && HubAccess::is_wall(&status(403)));
    assert!(!HubAccess::is_wall(&status(404)) && !HubAccess::is_wall(&status(500)));
    assert!(!HubAccess::is_wall(&HttpError::Io(std::io::Error::other("lost"))));
}

const GATE: &str = "nvidia/personaplex-7b-v1";

/// What a failed download's wall says, with the hub's record of the repository as this table has it.
fn access_after(rows: Vec<Row>, status: u16, token: &str) -> (Option<Value>, StandIn) {
    let hub = StandIn::table(rows);
    let wall = HttpError::Status(status, String::new());
    let access = HubAccess::after(&HttpClient::new(), hub.address(), &wall, GATE, token);
    (access, hub)
}

fn record_row(record: &Value) -> Row {
    TestHub::json(&format!("/api/models/{GATE}"), record)
}

#[test]
fn a_wall_at_a_gated_repository_names_its_page_and_whether_a_token_is_saved() {
    let (access, hub) = access_after(vec![record_row(&json!({"id": GATE, "gated": "auto"}))], 403, "hf_test");
    let page = format!("{}/{GATE}", hub.address());
    assert_eq!(access, Some(json!({"kind": "gated", "url": page, "repo": GATE, "status": 403, "tokenSet": true})));
    assert_eq!(hub.targets().len(), 1, "the record is read once");
    assert!(hub.asked()[0].contains("Authorization: Bearer hf_test\r\n"), "with the operator's token");
    let (manual, _) = access_after(vec![record_row(&json!({"id": GATE, "gated": "manual"}))], 403, "hf_test");
    assert_eq!(manual.unwrap()["kind"], json!("gated"), "a repository gated by hand is gated too");
    let (no_token, _) = access_after(vec![record_row(&json!({"id": GATE, "gated": "auto"}))], 401, "");
    let no_token = no_token.unwrap();
    assert_eq!((&no_token["status"], &no_token["tokenSet"]), (&json!(401), &json!(false)));
}

#[test]
fn a_wall_names_no_page_where_no_page_opens_the_door() {
    let open = vec![record_row(&json!({"id": GATE, "gated": false}))];
    assert_eq!(access_after(open, 403, "t").0, None, "not gated: a private one, a token the hub does not know");
    assert_eq!(
        access_after(Vec::new(), 403, "t").0,
        None,
        "a record the hub did not answer is unknown, and unknown is not gated"
    );
    assert_eq!(access_after(vec![record_row(&json!({"id": GATE}))], 403, "t").0, None, "a record that says nothing of a gate");
    assert_eq!(access_after(vec![record_row(&json!({"gated": "other"}))], 403, "t").0, None, "a word that is no gate");
}

#[test]
fn only_a_wall_asks_for_the_record_at_all() {
    let hub = StandIn::table(vec![record_row(&json!({"id": GATE, "gated": "auto"}))]);
    let client = HttpClient::new();
    assert!(HubAccess::after(&client, hub.address(), &HttpError::Status(404, String::new()), GATE, "t").is_none());
    let lost = HttpError::Io(std::io::Error::other("connection reset"));
    assert!(HubAccess::after(&client, hub.address(), &lost, GATE, "t").is_none());
    assert_eq!(hub.targets(), Vec::<String>::new());
}

#[test]
fn a_renamed_gated_repository_is_read_at_its_new_name() {
    let new = "nvidia/personaplex-8b";
    let (access, hub) = access_after(
        vec![
            TestHub::moved(&format!("/api/models/{GATE}"), &format!("/api/models/{new}")),
            TestHub::json(&format!("/api/models/{new}"), &json!({"id": new, "gated": "manual"})),
        ],
        403,
        "t",
    );
    assert_eq!(
        access.unwrap()["url"],
        json!(format!("{}/{GATE}", hub.address())),
        "the page is named as the operator asked for it"
    );
    assert_eq!(hub.targets(), [format!("/api/models/{GATE}"), format!("/api/models/{new}")]);
    assert!(hub.asked()[1].contains("Authorization: Bearer t\r\n"), "and the token goes along");
}

#[test]
fn a_repositorys_id_is_quoted_in_its_page_with_the_slash_kept() {
    let hub = StandIn::table(vec![TestHub::json("/api/models/a%20b/c%23d", &json!({"gated": "auto"}))]);
    let wall = HttpError::Status(403, String::new());
    let access = HubAccess::after(&HttpClient::new(), hub.address(), &wall, "a b/c#d", "").unwrap();
    assert_eq!(access["url"], json!(format!("{}/a%20b/c%23d", hub.address())));
    assert_eq!(access["repo"], json!("a b/c#d"));
}
