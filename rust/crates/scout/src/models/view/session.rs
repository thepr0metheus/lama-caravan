//! One connection with the kernel: its questions read, and each answered from the tree and the reader. The answers are made by value, so a test hands a request in and reads what comes out.

use crate::models::view::kernel::{Ask, Errno, KernelAnswer, KernelRequest};
use crate::models::view::reader::ViewBytes;
use crate::models::view::tree::{ViewNode, ViewTree};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{Read, Write};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError, mpsc};

/// The session of a mount.
pub struct ViewSession {
    tree: Arc<Mutex<ViewTree>>,
    bytes: Arc<dyn ViewBytes>,
    given: Arc<GivenBytes>,
}

/// How much of each file programs were given through the view since a start last asked for it. A program that maps its model reads no byte its own counters count: seamless's 9 GB showed as 0.13 GB
/// on the board's bar for the whole of its load (2026-11-03).
#[derive(Default)]
pub struct GivenBytes {
    by_file: Mutex<BTreeMap<String, u64>>,
}

impl GivenBytes {
    fn files(&self) -> MutexGuard<'_, BTreeMap<String, u64>> {
        self.by_file.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn under(file: &str, place: &str) -> bool {
        file == place || file.strip_prefix(place).is_some_and(|rest| rest.starts_with('/'))
    }

    fn add(&self, file: &str, count: u64) {
        *self.files().entry(file.to_string()).or_default() += count;
    }

    /// A start asks for `place`, a file or a folder: its count begins again.
    pub fn begin(&self, place: &str) {
        self.files().retain(|file, _| !Self::under(file, place));
    }

    /// What these places were given; `None` when nothing of them came this way.
    pub fn of(&self, places: &[String]) -> Option<u64> {
        let files = self.files();
        let mut given = files
            .iter()
            .filter(|(file, _)| places.iter().any(|place| Self::under(file, place)))
            .map(|(_, count)| *count)
            .peekable();
        given.peek()?;
        Some(given.sum())
    }
}

/// The threads that answer reads, each read to whichever is free. A read waits for the network, and the kernel hands requests over in their order: one thread that answered everything left a
/// question of what is in a folder behind every read of every program. The scout asks such questions under a cell's lock, and with a program reading by 26 threads `/api/state` stopped answering
/// for the whole of its load: the board drew the last thing it heard, and 150 requests stood in the scout (2026-11-03).
struct Readers {
    waiting: Option<mpsc::Sender<Vec<u8>>>,
}

impl Readers {
    /// How many read at once. Without FUSE's asynchronous reads a thread of a program waits for one read at a time, so more threads than this wait for a free reader and not for one another.
    const HOW_MANY: usize = 16;

    /// Started for this session on this device. None could start, and `take` refuses: the reads are answered in turn, slowly, and not lost.
    fn started(session: &Arc<ViewSession>, device: &File) -> Self {
        let (sender, receiver) = mpsc::channel::<Vec<u8>>();
        let receiver = Arc::new(Mutex::new(receiver));
        let mut any = false;
        for _ in 0..Self::HOW_MANY {
            let Ok(device) = device.try_clone() else {
                break;
            };
            let (session, receiver) = (Arc::clone(session), Arc::clone(&receiver));
            let reading = std::thread::Builder::new().name("library-read".to_string()).spawn(move || {
                Self::work(&session, device, &receiver);
            });
            any |= reading.is_ok();
        }
        Self { waiting: any.then_some(sender) }
    }

    /// Answers reads until the session goes or the mount does.
    fn work(session: &ViewSession, mut device: File, waiting: &Mutex<mpsc::Receiver<Vec<u8>>>) {
        loop {
            let next = waiting.lock().unwrap_or_else(PoisonError::into_inner).recv();
            let Ok(request) = next else {
                return;
            };
            if !ViewSession::said(&mut device, session.answer(&request)) {
                return;
            }
        }
    }

    /// Whether a reader will answer this.
    fn take(&self, request: &[u8]) -> bool {
        self.waiting.as_ref().is_some_and(|waiting| waiting.send(request.to_vec()).is_ok())
    }
}

impl ViewSession {
    /// The FUSE version these answers are laid out for.
    const MAJOR: u32 = 7;
    const MINOR: u32 = 31;
    /// A read may ask for this many pages: a program reading a model asks for a lot at once.
    const MAX_PAGES: u16 = 256;
    const MAX_READAHEAD: u32 = 1 << 20;
    const FLAG_MAX_PAGES: u32 = 1 << 22;
    /// Writes never come on a read-only mount, and the kernel wants a figure.
    const MAX_WRITE: u32 = 4096;
    /// What one request can take, the kernel's own rule for a mount that is not written to.
    const REQUEST_ROOM: usize = 1 << 16;
    /// The page cache may keep what it read of a file opened again: a file of one number does not change.
    const KEEP_CACHE: u32 = 1 << 1;

    /// A session over this tree.
    pub fn new(tree: Arc<Mutex<ViewTree>>, bytes: Arc<dyn ViewBytes>, given: Arc<GivenBytes>) -> Self {
        Self { tree, bytes, given }
    }

    /// Answers the kernel on `device` until the mount goes: what is where at once, here, and a read by a reader.
    pub fn serve(self, mut device: File) {
        const INTERRUPTED: [i32; 3] = [2, 4, 11];
        let session = Arc::new(self);
        let readers = Readers::started(&session, &device);
        let mut room = vec![0u8; Self::REQUEST_ROOM];
        loop {
            let count = match device.read(&mut room) {
                // The kernel never says nothing: this is a test's way of saying the mount is gone.
                Ok(0) => return,
                Ok(count) => count,
                Err(error) if error.raw_os_error().is_some_and(|code| INTERRUPTED.contains(&code)) => continue,
                // The mount is gone: ENODEV, and nothing more will come.
                Err(_) => return,
            };
            let Some(request) = room.get(..count) else {
                continue;
            };
            if Self::is_read(request) && readers.take(request) {
                continue;
            }
            if !Self::said(&mut device, session.answer(request)) {
                return;
            }
        }
    }

    fn is_read(request: &[u8]) -> bool {
        KernelRequest::read(request).is_some_and(|asked| asked.opcode == Ask::READ)
    }

    /// Writes this answer, when there is one; `false` when the mount is gone. A request given up while it was answered says ENOENT: nobody waits for it, and the next is read.
    fn said(device: &mut File, answer: Option<Vec<u8>>) -> bool {
        let Some(answer) = answer else {
            return true;
        };
        !matches!(device.write_all(&answer), Err(error) if error.raw_os_error() != Some(2))
    }

    /// The answer to these bytes; `None` for what takes no answer.
    pub fn answer(&self, request: &[u8]) -> Option<Vec<u8>> {
        let asked = KernelRequest::read(request)?;
        let unique = asked.unique;
        let refused = |errno| Some(KernelAnswer::error(unique, errno));
        match asked.opcode {
            Ask::FORGET | Ask::BATCH_FORGET | Ask::INTERRUPT => None,
            Ask::INIT => Some(Self::init(&asked)),
            Ask::LOOKUP => self.lookup(&asked).or_else(|| refused(Errno::ENOENT)),
            Ask::GETATTR => self.about(&asked).or_else(|| refused(Errno::ENOENT)),
            Ask::READLINK => self.link(&asked).or_else(|| refused(Errno::EINVAL)),
            Ask::OPEN => Some(self.open(&asked)),
            Ask::OPENDIR => Some(Self::opened(unique, 0)),
            Ask::READ => Some(self.read(&asked)),
            Ask::READDIR => Some(self.listing(&asked)),
            Ask::RELEASE | Ask::RELEASEDIR | Ask::DESTROY => Some(KernelAnswer::to(unique).done()),
            Ask::STATFS => Some(Self::statfs(unique)),
            _ => refused(Errno::ENOSYS),
        }
    }

    /// The first answer: this version, or, to a kernel of a later major version, the major version to ask again with.
    fn init(asked: &KernelRequest<'_>) -> Vec<u8> {
        let Some((major, minor, readahead)) = asked.init() else {
            return KernelAnswer::error(asked.unique, Errno::EINVAL);
        };
        KernelAnswer::to(asked.unique)
            .u32(Self::MAJOR)
            .u32(if major > Self::MAJOR { 0 } else { Self::MINOR.min(minor) })
            .u32(readahead.min(Self::MAX_READAHEAD))
            .u32(Self::FLAG_MAX_PAGES)
            // How many requests may wait, and from how many it is congested.
            .u16(16)
            .u16(12)
            .u32(Self::MAX_WRITE)
            // The moments' grain, the pages of a read, what the map is aligned to, and the fields unused.
            .u32(1)
            .u16(Self::MAX_PAGES)
            .u16(0)
            .bytes(&[0u8; 32])
            .done()
    }

    fn lookup(&self, asked: &KernelRequest<'_>) -> Option<Vec<u8>> {
        let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        let number = tree.lookup(asked.node, asked.name()?)?;
        Some(KernelAnswer::to(asked.unique).entry(number, tree.node(number)?, asked.uid, asked.gid).done())
    }

    fn about(&self, asked: &KernelRequest<'_>) -> Option<Vec<u8>> {
        let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        Some(KernelAnswer::to(asked.unique).about(asked.node, tree.node(asked.node)?, asked.uid, asked.gid).done())
    }

    fn link(&self, asked: &KernelRequest<'_>) -> Option<Vec<u8>> {
        let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        match tree.node(asked.node)? {
            ViewNode::Link(target) => Some(KernelAnswer::to(asked.unique).bytes(target.as_bytes()).done()),
            _ => None,
        }
    }

    fn opened(unique: u64, flags: u32) -> Vec<u8> {
        KernelAnswer::to(unique).u64(0).u32(flags).u32(0).done()
    }

    fn open(&self, asked: &KernelRequest<'_>) -> Vec<u8> {
        let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        match tree.node(asked.node) {
            Some(ViewNode::File { .. }) => Self::opened(asked.unique, Self::KEEP_CACHE),
            Some(_) => KernelAnswer::error(asked.unique, Errno::EISDIR),
            None => KernelAnswer::error(asked.unique, Errno::ENOENT),
        }
    }

    fn read(&self, asked: &KernelRequest<'_>) -> Vec<u8> {
        let unique = asked.unique;
        let Some((offset, size)) = asked.span() else {
            return KernelAnswer::error(unique, Errno::EINVAL);
        };
        let file = {
            let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
            tree.node(asked.node).cloned()
        };
        let Some(ViewNode::File { rel, size: total }) = file else {
            return KernelAnswer::error(unique, Errno::EISDIR);
        };
        match self.bytes.read_at(&rel, offset, size, total) {
            Ok(bytes) => {
                self.given.add(&rel, bytes.len() as u64);
                KernelAnswer::to(unique).bytes(&bytes).done()
            }
            // The program hears a failed read: a cell that cannot read its model says so and stops, where a read that waits for ever would look like a load that goes on.
            Err(_) => KernelAnswer::error(unique, Errno::EIO),
        }
    }

    fn listing(&self, asked: &KernelRequest<'_>) -> Vec<u8> {
        let unique = asked.unique;
        let Some((from, room)) = asked.span() else {
            return KernelAnswer::error(unique, Errno::EINVAL);
        };
        let tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(ViewNode::Folder(names)) = tree.node(asked.node) else {
            return KernelAnswer::error(unique, Errno::ENOTDIR);
        };
        let rows = [(".".to_string(), asked.node), ("..".to_string(), ViewTree::ROOT)]
            .into_iter()
            .chain(names.iter().map(|(name, number)| (name.clone(), *number)));
        let mut answer = KernelAnswer::to(unique);
        let mut used = 0;
        for (at, (name, number)) in rows.enumerate().skip(usize::try_from(from).unwrap_or(usize::MAX)) {
            used += KernelAnswer::listed_size(&name);
            if used > room as usize {
                break;
            }
            answer = answer.listed(number, at as u64 + 1, &name, tree.node(number));
        }
        answer.done()
    }

    /// The mount holds no room of its own: nothing is written to it. The block size and the longest name are what a program asks.
    fn statfs(unique: u64) -> Vec<u8> {
        KernelAnswer::to(unique).bytes(&[0u8; 40]).u32(4096).u32(255).u32(4096).bytes(&[0u8; 28]).done()
    }
}
