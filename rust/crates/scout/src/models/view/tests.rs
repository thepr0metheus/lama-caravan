//! The view, by value: what the kernel is told for each thing it asks, what the reader asks of the controller, and, where the machine can, a real mount read through.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::kernel::{Ask, Errno};
use super::reader::{ControllerFiles, ControllerReader, ViewBytes};
use super::session::{GivenBytes, ViewSession};
use super::tree::{ViewNode, ViewTree};
use super::*;
use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use crate::tests::{StandIn, TestFolder};
use serde_json::json;
use std::collections::BTreeMap;
use std::io::{self, Read, Seek, SeekFrom};
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::sync::mpsc;
use std::time::Duration;

const MODEL: &str = "org/a/q4/a-Q4.gguf";

/// The bytes of a test, by file.
struct Table(BTreeMap<String, Vec<u8>>);

impl ViewBytes for Table {
    fn read_at(&self, rel: &str, offset: u64, size: u32, _total: u64) -> io::Result<Vec<u8>> {
        let bytes = self.0.get(rel).ok_or_else(|| io::Error::other("gone"))?;
        let from = (offset as usize).min(bytes.len());
        let to = (from + size as usize).min(bytes.len());
        Ok(bytes[from..to].to_vec())
    }
}

/// A request as the kernel lays it out.
fn asked(opcode: u32, unique: u64, node: u64, body: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(&(40 + body.len() as u32).to_ne_bytes());
    out.extend_from_slice(&opcode.to_ne_bytes());
    out.extend_from_slice(&unique.to_ne_bytes());
    out.extend_from_slice(&node.to_ne_bytes());
    out.extend_from_slice(&1000u32.to_ne_bytes());
    out.extend_from_slice(&1001u32.to_ne_bytes());
    out.extend_from_slice(&[0u8; 8]);
    out.extend_from_slice(body);
    out
}

fn read_body(offset: u64, size: u32) -> Vec<u8> {
    let mut out = vec![0u8; 8];
    out.extend_from_slice(&offset.to_ne_bytes());
    out.extend_from_slice(&size.to_ne_bytes());
    out.extend_from_slice(&[0u8; 20]);
    out
}

fn u32_at(bytes: &[u8], at: usize) -> u32 {
    u32::from_ne_bytes(bytes[at..at + 4].try_into().unwrap())
}

fn u64_at(bytes: &[u8], at: usize) -> u64 {
    u64::from_ne_bytes(bytes[at..at + 8].try_into().unwrap())
}

fn i32_at(bytes: &[u8], at: usize) -> i32 {
    i32::from_ne_bytes(bytes[at..at + 4].try_into().unwrap())
}

/// A session over one file and one link.
fn session() -> (ViewSession, u64) {
    let tree = Arc::new(Mutex::new(ViewTree::default()));
    let file = tree.lock().unwrap().offer_file(MODEL, 10).unwrap();
    tree.lock().unwrap().offer_link("org/a/q4/link.gguf", "a-Q4.gguf").unwrap();
    let bytes = Table(BTreeMap::from([(MODEL.to_string(), b"0123456789".to_vec())]));
    (ViewSession::new(tree, Arc::new(bytes), Arc::default()), file)
}

#[test]
fn the_tree_holds_what_was_offered_and_nothing_that_leaves_it() {
    let mut tree = ViewTree::default();
    let file = tree.offer_file(MODEL, 7).unwrap();
    assert_eq!(tree.offer_file(MODEL, 7).unwrap(), file, "the same file keeps its number");
    let org = tree.lookup(ViewTree::ROOT, "org").unwrap();
    assert!(matches!(tree.node(org), Some(ViewNode::Folder(_))));
    let newer = tree.offer_file(MODEL, 8).unwrap();
    assert_ne!(newer, file, "another file under the old name is another thing");
    assert_eq!(
        tree.node(file),
        Some(&ViewNode::File { rel: MODEL.to_string(), size: 7 }),
        "a program that has it open goes on reading what it opened"
    );
    for bad in ["../up.gguf", "/abs.gguf", "a/../b.gguf", ""] {
        assert!(tree.offer_file(bad, 1).is_err(), "{bad}");
    }
    assert!(tree.offer_file("org/a/q4/a-Q4.gguf/inside", 1).is_err(), "a file is no folder");
    assert_eq!(tree.lookup(ViewTree::ROOT, "nothing"), None);
    assert_eq!(tree.lookup(file, "anything"), None, "a file holds no names");
}

#[test]
fn the_first_answer_says_the_version_and_a_read_of_a_megabyte() {
    let (session, _) = session();
    let mut body = Vec::new();
    for word in [7u32, 42, 1 << 24, 0] {
        body.extend_from_slice(&word.to_ne_bytes());
    }
    let answer = session.answer(&asked(Ask::INIT, 5, 0, &body)).unwrap();
    assert_eq!(answer.len(), 16 + 64, "the size a kernel of this minor version reads");
    assert_eq!(u32_at(&answer, 0) as usize, answer.len());
    assert_eq!(i32_at(&answer, 4), 0);
    assert_eq!(u64_at(&answer, 8), 5, "its number is the request's");
    assert_eq!((u32_at(&answer, 16), u32_at(&answer, 20)), (7, 31));
    assert_eq!(u32_at(&answer, 24), 1 << 20, "the read-ahead: no more than it can hold");
    assert_eq!(u32_at(&answer, 28), 1 << 22, "the flag that makes a read of many pages possible");
    assert_eq!(u16::from_ne_bytes(answer[44..46].try_into().unwrap()), 256);
    let mut body = Vec::new();
    for word in [8u32, 5, 4096, 0] {
        body.extend_from_slice(&word.to_ne_bytes());
    }
    let later = session.answer(&asked(Ask::INIT, 6, 0, &body)).unwrap();
    assert_eq!(
        (u32_at(&later, 16), u32_at(&later, 20)),
        (7, 0),
        "a kernel of a later major version is told which to ask again with"
    );
    assert_eq!(i32_at(&session.answer(&asked(Ask::INIT, 7, 0, b"")).unwrap(), 4), -Errno::EINVAL);
}

#[test]
fn a_name_is_answered_with_what_it_is() {
    let (session, file) = session();
    let name = |word: &str| [word.as_bytes(), b"\0"].concat();
    let org = session.answer(&asked(Ask::LOOKUP, 1, ViewTree::ROOT, &name("org"))).unwrap();
    assert_eq!(u32_at(&org, 0), 16 + 128);
    assert_eq!(u32_at(&org, 16 + 40 + 60), 0o040_555, "a folder, read and entered by anyone");
    let a = u64_at(&org, 16);
    let a = u64_at(&session.answer(&asked(Ask::LOOKUP, 2, a, &name("a"))).unwrap(), 16);
    let q4 = u64_at(&session.answer(&asked(Ask::LOOKUP, 3, a, &name("q4"))).unwrap(), 16);
    let found = session.answer(&asked(Ask::LOOKUP, 4, q4, &name("a-Q4.gguf"))).unwrap();
    assert_eq!(u64_at(&found, 16), file);
    assert_eq!(u64_at(&found, 16 + 40 + 8), 10, "what it weighs");
    assert_eq!(u32_at(&found, 16 + 40 + 60), 0o100_444, "a file nobody writes");
    assert_eq!((u32_at(&found, 16 + 40 + 68), u32_at(&found, 16 + 40 + 72)), (1000, 1001), "it is the asker's");
    let missing = session.answer(&asked(Ask::LOOKUP, 5, q4, &name("nothing"))).unwrap();
    assert_eq!((u32_at(&missing, 0), i32_at(&missing, 4)), (16, -Errno::ENOENT));
    let about = session.answer(&asked(Ask::GETATTR, 6, file, &[0u8; 16])).unwrap();
    assert_eq!(u32_at(&about, 0), 16 + 104);
    assert_eq!(u64_at(&about, 16 + 16 + 8), 10);
    assert_eq!(i32_at(&session.answer(&asked(Ask::GETATTR, 7, 999, &[0u8; 16])).unwrap(), 4), -Errno::ENOENT);
}

#[test]
fn a_read_gets_its_bytes_and_a_failed_one_says_so() {
    let (session, file) = session();
    let read =
        |session: &ViewSession, offset, size, node| session.answer(&asked(Ask::READ, 9, node, &read_body(offset, size))).unwrap();
    let whole = read(&session, 0, 4, file);
    assert_eq!(&whole[16..], b"0123");
    assert_eq!(u32_at(&whole, 0), 20);
    assert_eq!(&read(&session, 8, 100, file)[16..], b"89", "fewer only where the file ends");
    assert_eq!(u32_at(&read(&session, 50, 100, file), 0), 16, "past the end: nothing, and no error");
    assert_eq!(i32_at(&read(&session, 0, 1, ViewTree::ROOT), 4), -Errno::EISDIR);
    let tree = Arc::new(Mutex::new(ViewTree::default()));
    let gone = tree.lock().unwrap().offer_file("gone.gguf", 5).unwrap();
    let failing = ViewSession::new(tree, Arc::new(Table(BTreeMap::new())), Arc::default());
    assert_eq!(
        i32_at(&failing.answer(&asked(Ask::READ, 9, gone, &read_body(0, 1))).unwrap(), 4),
        -Errno::EIO,
        "the program hears it, and does not wait for ever"
    );
}

#[test]
fn opening_listing_and_following_a_link() {
    let (session, file) = session();
    let opened = session.answer(&asked(Ask::OPEN, 1, file, &[0u8; 8])).unwrap();
    assert_eq!(u32_at(&opened, 0), 32);
    assert_eq!(u32_at(&opened, 24), 1 << 1, "the page cache may keep a file of one number");
    assert_eq!(i32_at(&session.answer(&asked(Ask::OPEN, 2, ViewTree::ROOT, &[0u8; 8])).unwrap(), 4), -Errno::EISDIR);
    let names = |answer: &[u8]| {
        let (mut out, mut at) = (Vec::new(), 16);
        while at < answer.len() {
            let length = u32_at(answer, at + 16) as usize;
            out.push((
                String::from_utf8(answer[at + 24..at + 24 + length].to_vec()).unwrap(),
                u64_at(answer, at + 8),
                u32_at(answer, at + 20),
            ));
            at += 24 + length.next_multiple_of(8);
        }
        out
    };
    let top = session.answer(&asked(Ask::READDIR, 3, ViewTree::ROOT, &read_body(0, 4096))).unwrap();
    assert_eq!(names(&top), [(".".to_string(), 1, 4), ("..".to_string(), 2, 4), ("org".to_string(), 3, 4)]);
    let on = session.answer(&asked(Ask::READDIR, 4, ViewTree::ROOT, &read_body(2, 4096))).unwrap();
    assert_eq!(names(&on), [("org".to_string(), 3, 4)], "from where the last listing stopped");
    let short = session.answer(&asked(Ask::READDIR, 5, ViewTree::ROOT, &read_body(0, 40))).unwrap();
    assert_eq!(names(&short).len(), 1, "no more than the room it gave");
    assert_eq!(i32_at(&session.answer(&asked(Ask::READDIR, 6, file, &read_body(0, 4096))).unwrap(), 4), -Errno::ENOTDIR);
    let org = u64_at(&session.answer(&asked(Ask::LOOKUP, 7, ViewTree::ROOT, b"org\0")).unwrap(), 16);
    let a = u64_at(&session.answer(&asked(Ask::LOOKUP, 8, org, b"a\0")).unwrap(), 16);
    let q4 = u64_at(&session.answer(&asked(Ask::LOOKUP, 9, a, b"q4\0")).unwrap(), 16);
    let inside = session.answer(&asked(Ask::READDIR, 10, q4, &read_body(0, 4096))).unwrap();
    assert_eq!(
        names(&inside)[2..].iter().map(|row| (row.0.as_str(), row.2)).collect::<Vec<_>>(),
        [("a-Q4.gguf", 8), ("link.gguf", 10)],
        "a file and a link say what they are"
    );
    let link = u64_at(&session.answer(&asked(Ask::LOOKUP, 11, q4, b"link.gguf\0")).unwrap(), 16);
    assert_eq!(&session.answer(&asked(Ask::READLINK, 12, link, b"")).unwrap()[16..], b"a-Q4.gguf");
    assert_eq!(i32_at(&session.answer(&asked(Ask::READLINK, 13, file, b"")).unwrap(), 4), -Errno::EINVAL);
}

#[test]
fn what_takes_no_answer_gets_none_and_what_is_not_done_here_says_so() {
    let (session, _) = session();
    for opcode in [Ask::FORGET, Ask::BATCH_FORGET, Ask::INTERRUPT] {
        assert_eq!(session.answer(&asked(opcode, 1, 1, &[0u8; 8])), None, "{opcode}");
    }
    for opcode in [Ask::RELEASE, Ask::RELEASEDIR, Ask::DESTROY] {
        assert_eq!(u32_at(&session.answer(&asked(opcode, 1, 1, &[0u8; 8])).unwrap(), 0), 16, "{opcode}");
    }
    let statfs = session.answer(&asked(Ask::STATFS, 1, 1, b"")).unwrap();
    assert_eq!(u32_at(&statfs, 0), 16 + 80);
    assert_eq!(u32_at(&statfs, 16 + 44), 255, "the longest name");
    assert_eq!(i32_at(&session.answer(&asked(99, 1, 1, b"")).unwrap(), 4), -Errno::ENOSYS);
    assert_eq!(session.answer(b"too short"), None);
}

#[test]
fn what_a_program_was_given_is_counted_by_file_and_a_start_counts_anew() {
    let tree = Arc::new(Mutex::new(ViewTree::default()));
    let (one, two, other) = {
        let mut tree = tree.lock().unwrap();
        (
            tree.offer_file("fold/x/a.bin", 10).unwrap(),
            tree.offer_file("fold/x/b.bin", 10).unwrap(),
            tree.offer_file("fold/xy/a.bin", 10).unwrap(),
        )
    };
    let bytes = BTreeMap::from([
        ("fold/x/a.bin".to_string(), vec![1u8; 10]),
        ("fold/x/b.bin".to_string(), vec![2u8; 10]),
        ("fold/xy/a.bin".to_string(), vec![3u8; 10]),
    ]);
    let given = Arc::new(GivenBytes::default());
    let session = ViewSession::new(tree, Arc::new(Table(bytes)), Arc::clone(&given));
    let places = |place: &str| vec![place.to_string()];
    assert_eq!(given.of(&places("fold/x")), None, "nothing came this way: not a zero, for the process's own count may say more");
    for (unique, (node, size)) in [(one, 4), (two, 3), (other, 9)].into_iter().enumerate() {
        session.answer(&asked(Ask::READ, unique as u64, node, &read_body(0, size))).unwrap();
    }
    assert_eq!(given.of(&places("fold/x")), Some(7), "a folder is what its files were given, and fold/xy is not in it");
    assert_eq!(given.of(&places("fold/x/a.bin")), Some(4), "a file by itself");
    assert_eq!(given.of(&["fold/x/b.bin".to_string(), "fold/xy/a.bin".to_string()]), Some(12), "the files of a start together");
    given.begin("fold/x");
    assert_eq!(given.of(&places("fold/x")), None, "a start counts anew");
    assert_eq!(given.of(&places("fold/xy")), Some(9), "another model's goes on");
}

/// Bytes that say a read has come and give nothing until the test lets them.
struct AtAGate {
    came: mpsc::Sender<u64>,
    gate: Mutex<mpsc::Receiver<()>>,
}

impl ViewBytes for AtAGate {
    fn read_at(&self, _rel: &str, offset: u64, size: u32, _total: u64) -> io::Result<Vec<u8>> {
        self.came.send(offset).unwrap();
        assert!(self.gate.lock().unwrap().recv().is_err(), "nothing is sent, only the end");
        Ok(vec![7; size as usize])
    }
}

#[test]
fn a_question_is_answered_while_reads_wait_and_a_read_does_not_wait_for_another() {
    let tree = Arc::new(Mutex::new(ViewTree::default()));
    let file = tree.lock().unwrap().offer_file(MODEL, 10).unwrap();
    let (came, reads) = mpsc::channel();
    let (opens, gate) = mpsc::channel::<()>();
    let session = ViewSession::new(tree, Arc::new(AtAGate { came, gate: Mutex::new(gate) }), Arc::default());
    // A pair of sockets of whole messages is what the kernel's device is to the session.
    let (kernel, device) = UnixDatagram::pair().unwrap();
    kernel.set_read_timeout(Some(Duration::from_secs(20))).unwrap();
    let serving = std::thread::spawn(move || session.serve(fs::File::from(OwnedFd::from(device))));
    // More reads than there are readers, as many as the threads of a program ask.
    for at in 0..20u64 {
        kernel.send(&asked(Ask::READ, at + 1, file, &read_body(at, 1))).unwrap();
    }
    let wait = Duration::from_secs(20);
    for _ in 0..16 {
        reads.recv_timeout(wait).expect("a read does not wait for another");
    }
    let mut room = [0u8; 4096];
    let answer = |room: &mut [u8; 4096]| {
        kernel.recv(room).unwrap();
        u64_at(room, 8)
    };
    kernel.send(&asked(Ask::GETATTR, 21, file, &[0u8; 16])).unwrap();
    assert_eq!(answer(&mut room), 21, "asked after the reads, answered before them: a question does not wait for the network");
    kernel.send(&asked(Ask::LOOKUP, 22, ViewTree::ROOT, b"org\0")).unwrap();
    assert_eq!(answer(&mut room), 22);
    drop(opens);
    let mut answered: Vec<u64> = (0..20).map(|_| answer(&mut room)).collect();
    answered.sort_unstable();
    assert_eq!(answered, (1..=20).collect::<Vec<u64>>(), "and the reads are answered, each by its own number");
    kernel.send(&[]).unwrap();
    serving.join().unwrap();
}

/// A controller of one file that gives parts, as `serve_file` gives them.
fn parts_of(bytes: Vec<u8>) -> StandIn {
    StandIn::serving(move |head| {
        if !head.contains("/api/models/download?path=") {
            return StandIn::answer("404 Not Found", b"");
        }
        let range = head.lines().find_map(|line| line.strip_prefix("Range: bytes=")).unwrap_or("0-");
        let (from, to) = range.trim().split_once('-').unwrap();
        let from: usize = from.parse().unwrap();
        if from >= bytes.len() {
            return format!("HTTP/1.1 416 Range Not Satisfiable\r\nContent-Length: 0\r\nContent-Range: bytes */{}\r\nConnection: close\r\n\r\n", bytes.len()).into_bytes();
        }
        let to: usize = to.parse::<usize>().map_or(bytes.len() - 1, |to| to.min(bytes.len() - 1));
        let part = &bytes[from..=to];
        let mut out = format!(
            "HTTP/1.1 206 Partial Content\r\nContent-Length: {}\r\nContent-Range: bytes {from}-{to}/{}\r\nConnection: close\r\n\r\n",
            part.len(),
            bytes.len()
        )
        .into_bytes();
        out.extend_from_slice(part);
        out
    })
}

fn files_of(folder: &TestFolder, controller: &StandIn) -> ControllerFiles {
    fs::write(
        folder.path.join("config.json"),
        json!({"controllerUrl": controller.address(), "controllerToken": "fleet"}).to_string(),
    )
    .unwrap();
    ControllerFiles::new(Arc::new(ScoutConfig::load(&folder.path.join("config.json")).unwrap()), Arc::new(HttpClient::new()))
}

fn counted(size: usize) -> Vec<u8> {
    (0..size).map(|at| (at % 251) as u8).collect()
}

#[test]
fn a_file_read_through_asks_the_controller_once_a_window_and_says_who_asks() {
    let folder = TestFolder::new("view-window");
    let bytes = counted(1 << 16);
    let controller = parts_of(bytes.clone());
    let files = Arc::new(files_of(&folder, &controller));
    assert_eq!(files.size_of(MODEL).unwrap(), bytes.len() as u64);
    let asked_before = controller.targets().len();
    let reader = ControllerReader::resting(Arc::clone(&files), vec![]);
    let total = bytes.len() as u64;
    let mut out = Vec::new();
    while (out.len() as u64) < total {
        out.extend(reader.read_at(MODEL, out.len() as u64, 4096, total).unwrap());
    }
    assert_eq!(out, bytes);
    assert_eq!(controller.targets().len() - asked_before, 1, "one window: a program reading through does not ask at every read");
    assert!(controller.asked().iter().all(|head| head.contains("X-Caravan-Token: fleet")), "the fleet's token goes along");
    assert_eq!(reader.read_at(MODEL, total + 5, 10, total).unwrap(), Vec::<u8>::new(), "past the end: nobody is asked");
    assert_eq!(controller.targets().len() - asked_before, 1);
}

#[test]
fn a_read_near_ahead_stays_in_its_window_and_one_elsewhere_opens_another() {
    let folder = TestFolder::new("view-seek");
    let bytes = counted(1 << 16);
    let controller = parts_of(bytes.clone());
    let files = Arc::new(files_of(&folder, &controller));
    let reader = ControllerReader::resting(files, vec![]);
    let total = bytes.len() as u64;
    assert_eq!(reader.read_at(MODEL, 0, 10, total).unwrap(), &bytes[..10]);
    assert_eq!(reader.read_at(MODEL, 1000, 10, total).unwrap(), &bytes[1000..1010], "a small gap is read and dropped");
    assert_eq!(controller.targets().len(), 1);
    assert_eq!(reader.read_at(MODEL, 5, 10, total).unwrap(), &bytes[5..15], "back: another window");
    assert_eq!(controller.targets().len(), 2);
}

#[test]
fn a_read_takes_the_window_nearest_before_it() {
    let folder = TestFolder::new("view-nearest");
    let bytes = counted(1 << 16);
    let controller = parts_of(bytes.clone());
    let reader = ControllerReader::resting(Arc::new(files_of(&folder, &controller)), vec![]);
    let total = bytes.len() as u64;
    let read = |at: u64| assert_eq!(reader.read_at(MODEL, at, 10, total).unwrap(), &bytes[at as usize..at as usize + 10]);
    read(1000);
    read(500);
    read(1010);
    assert_eq!(controller.targets().len(), 2, "one window from 1000 and one from 500");
    read(1500);
    read(600);
    assert_eq!(controller.targets().len(), 2, "the window at 1020 took 1500, and the one at 510 is still there for 600");
}

#[test]
fn a_program_reading_many_places_keeps_a_window_at_each() {
    let folder = TestFolder::new("view-places");
    let bytes = counted(1 << 16);
    let controller = parts_of(bytes.clone());
    let reader = ControllerReader::resting(Arc::new(files_of(&folder, &controller)), vec![]);
    let total = bytes.len() as u64;
    // A place below the others cannot be read from their windows: each opens its own, as the threads of one copy do.
    let places: Vec<u64> = (0..26).rev().map(|place| place * 1000).collect();
    for at in places.iter().chain(&places) {
        let at = *at + u64::from(controller.targets().len() as u32 >= 26) * 10;
        assert_eq!(reader.read_at(MODEL, at, 10, total).unwrap(), &bytes[at as usize..at as usize + 10]);
    }
    assert_eq!(controller.targets().len(), 26, "each stays open for the next read at its place");
}

#[test]
fn threads_read_at_once_and_each_hears_its_own_bytes() {
    let folder = TestFolder::new("view-threads");
    let bytes = Arc::new(counted(1 << 16));
    let controller = parts_of(bytes.to_vec());
    let reader = Arc::new(ControllerReader::resting(Arc::new(files_of(&folder, &controller)), vec![Duration::ZERO; 3]));
    let total = bytes.len() as u64;
    let threads: Vec<_> = (0..8u64)
        .map(|thread| {
            let (reader, bytes) = (Arc::clone(&reader), Arc::clone(&bytes));
            std::thread::spawn(move || {
                for step in 0..200u64 {
                    let at = (thread * 8000 + step * 40) % (total - 100);
                    assert_eq!(reader.read_at(MODEL, at, 40, total).unwrap(), &bytes[at as usize..at as usize + 40]);
                }
            })
        })
        .collect();
    for thread in threads {
        thread.join().unwrap();
    }
}

#[test]
fn a_cut_answer_is_asked_again_and_one_that_stays_cut_says_so() {
    let folder = TestFolder::new("view-cut");
    let bytes = counted(1000);
    let whole = parts_of(bytes.clone());
    let tries = Arc::new(Mutex::new(0));
    let counted_tries = Arc::clone(&tries);
    let address = whole.address().to_string();
    let flaky = StandIn::serving(move |head| {
        let mut tries = counted_tries.lock().unwrap();
        *tries += 1;
        if *tries == 1 {
            return b"HTTP/1.1 206 Partial Content\r\nContent-Length: 1000\r\nConnection: close\r\n\r\nshort".to_vec();
        }
        drop(tries);
        let mut asked = std::net::TcpStream::connect(address.trim_start_matches("http://")).unwrap();
        io::Write::write_all(&mut asked, head.as_bytes()).unwrap();
        let mut out = Vec::new();
        asked.read_to_end(&mut out).unwrap();
        out
    });
    let files = Arc::new(files_of(&folder, &flaky));
    let reader = ControllerReader::resting(Arc::clone(&files), vec![Duration::ZERO]);
    assert_eq!(reader.read_at(MODEL, 0, 100, 1000).unwrap(), &bytes[..100]);
    assert_eq!(*tries.lock().unwrap(), 2);
    let down = StandIn::serving(|_| StandIn::answer("502 Bad Gateway", b"down"));
    let reader = ControllerReader::resting(Arc::new(files_of(&folder, &down)), vec![Duration::ZERO]);
    assert!(reader.read_at(MODEL, 0, 100, 1000).is_err());
    assert_eq!(down.targets().len(), 2, "the tries it was given, and then the program hears");
}

#[test]
fn what_a_file_weighs_is_asked_and_a_controller_that_gives_no_parts_is_named() {
    let folder = TestFolder::new("view-size");
    let empty = parts_of(Vec::new());
    assert_eq!(files_of(&folder, &empty).size_of(MODEL).unwrap(), 0, "a file of nothing");
    let old = StandIn::serving(|_| StandIn::answer("200 OK", b"the whole file"));
    let refused = files_of(&folder, &old).size_of(MODEL).unwrap_err();
    assert!(refused.message.contains("update it"), "{refused:?}");
    let none = StandIn::serving(|_| StandIn::answer("404 Not Found", b"nothing here"));
    let refused = files_of(&folder, &none).size_of(MODEL).unwrap_err();
    assert_eq!(refused.status, 404);
}

/// On a machine that has FUSE: the whole way, as a program reads it. Elsewhere it says so and passes: a container without the device is not the machine this is for.
#[test]
fn a_real_mount_reads_what_the_controller_holds() {
    if !FuseLink::available() {
        Log::line("view: no FUSE on this machine: the real mount was not tried");
        return;
    }
    let folder = TestFolder::new("view-mount");
    let bytes = counted(5 << 20);
    let controller = parts_of(bytes.clone());
    let view = LibraryView::new(folder.path.join("view"), files_of(&folder, &controller));
    let path = view.file(MODEL, Some(&json!({"size": bytes.len()}))).unwrap();
    assert!(view.holds(&path));
    let mut file = fs::File::open(&path).unwrap();
    assert_eq!(file.metadata().unwrap().len(), bytes.len() as u64);
    let mut read = Vec::new();
    file.read_to_end(&mut read).unwrap();
    assert_eq!(read, bytes, "the bytes the controller holds, through the kernel");
    file.seek(SeekFrom::Start(4 << 20)).unwrap();
    let mut some = [0u8; 16];
    file.read_exact(&mut some).unwrap();
    assert_eq!(&some[..], &bytes[4 << 20..(4 << 20) + 16]);
    assert!(fs::write(&path, b"x").is_err(), "nothing is written there");
    let listing =
        json!({"files": [{"path": "config.json", "size": 3}], "links": [{"path": "again.json", "target": "config.json"}]});
    let model_folder = view.folder_of("fold/x", &listing).unwrap();
    assert_eq!(fs::read_link(model_folder.join("again.json")).unwrap(), Path::new("config.json"));
    let names: Vec<String> =
        fs::read_dir(&model_folder).unwrap().map(|row| row.unwrap().file_name().to_string_lossy().into_owned()).collect();
    assert_eq!(names.len(), 2, "{names:?}");
    drop(file);
    FuseLink::unmount(view.folder());
}
