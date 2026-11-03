//! The kernel's side of FUSE, by value: what a request says and how an answer is laid out (include/uapi/linux/fuse.h). No file and no socket here: the session reads and writes, and a test hands bytes in.

use crate::models::view::tree::ViewNode;

/// What the kernel asks: only what a mount that is read and never written needs.
pub struct Ask;

impl Ask {
    /// A name in a folder.
    pub const LOOKUP: u32 = 1;
    /// It no longer holds a number: no answer.
    pub const FORGET: u32 = 2;
    /// What a thing is.
    pub const GETATTR: u32 = 3;
    /// Where a link points.
    pub const READLINK: u32 = 5;
    /// A file opened.
    pub const OPEN: u32 = 14;
    /// Bytes of a file.
    pub const READ: u32 = 15;
    /// What the mount holds.
    pub const STATFS: u32 = 17;
    /// A file closed.
    pub const RELEASE: u32 = 18;
    /// The first request of a connection.
    pub const INIT: u32 = 26;
    /// A folder opened.
    pub const OPENDIR: u32 = 27;
    /// A folder's names.
    pub const READDIR: u32 = 28;
    /// A folder closed.
    pub const RELEASEDIR: u32 = 29;
    /// A request given up: no answer.
    pub const INTERRUPT: u32 = 36;
    /// The connection ends.
    pub const DESTROY: u32 = 38;
    /// Many numbers no longer held: no answer.
    pub const BATCH_FORGET: u32 = 42;
}

/// The system's error numbers an answer says.
pub struct Errno;

impl Errno {
    /// No such file.
    pub const ENOENT: i32 = 2;
    /// A read that failed.
    pub const EIO: i32 = 5;
    /// A file asked to be a folder.
    pub const ENOTDIR: i32 = 20;
    /// A folder asked to be read as a file.
    pub const EISDIR: i32 = 21;
    /// Asked for what cannot be.
    pub const EINVAL: i32 = 22;
    /// Not done here: the kernel does not ask again.
    pub const ENOSYS: i32 = 38;
}

/// One request as it came.
#[derive(Debug, PartialEq, Eq)]
pub struct KernelRequest<'bytes> {
    /// What it asks.
    pub opcode: u32,
    /// The number its answer carries.
    pub unique: u64,
    /// The thing it asks of.
    pub node: u64,
    /// Who asks.
    pub uid: u32,
    /// Their group.
    pub gid: u32,
    /// The rest of it.
    pub body: &'bytes [u8],
}

impl<'bytes> KernelRequest<'bytes> {
    const HEAD: usize = 40;

    fn u32_at(bytes: &[u8], at: usize) -> Option<u32> {
        Some(u32::from_ne_bytes(bytes.get(at..at + 4)?.try_into().ok()?))
    }

    fn u64_at(bytes: &[u8], at: usize) -> Option<u64> {
        Some(u64::from_ne_bytes(bytes.get(at..at + 8)?.try_into().ok()?))
    }

    /// The request in these bytes; `None` for what is too short to be one.
    pub fn read(bytes: &'bytes [u8]) -> Option<Self> {
        Some(Self {
            opcode: Self::u32_at(bytes, 4)?,
            unique: Self::u64_at(bytes, 8)?,
            node: Self::u64_at(bytes, 16)?,
            uid: Self::u32_at(bytes, 24)?,
            gid: Self::u32_at(bytes, 28)?,
            body: bytes.get(Self::HEAD..)?,
        })
    }

    /// A name in the body, its zero at the end.
    pub fn name(&self) -> Option<&str> {
        let end = self.body.iter().position(|byte| *byte == 0)?;
        std::str::from_utf8(self.body.get(..end)?).ok()
    }

    /// (where, how many) of a read, or of a folder's listing: its first field is the handle.
    pub fn span(&self) -> Option<(u64, u32)> {
        Some((Self::u64_at(self.body, 8)?, Self::u32_at(self.body, 16)?))
    }

    /// (major, minor, the read-ahead it allows) of the first request.
    pub fn init(&self) -> Option<(u32, u32, u32)> {
        Some((Self::u32_at(self.body, 0)?, Self::u32_at(self.body, 4)?, Self::u32_at(self.body, 8)?))
    }
}

/// An answer on its way: its head is written when it is done.
pub struct KernelAnswer {
    out: Vec<u8>,
}

impl KernelAnswer {
    /// How long the kernel may keep a name and what it is, seconds: a start may show another file under an old name.
    const VALID_SEC: u64 = 1;
    const FILE: u32 = 0o100_444;
    const FOLDER: u32 = 0o040_555;
    const LINK: u32 = 0o120_777;
    const BLOCK: u32 = 4096;

    /// An answer to request `unique`.
    pub fn to(unique: u64) -> Self {
        let mut out = vec![0u8; 8];
        out.extend_from_slice(&unique.to_ne_bytes());
        Self { out }
    }

    /// An answer that is this error alone.
    pub fn error(unique: u64, errno: i32) -> Vec<u8> {
        let mut answer = Self::to(unique);
        if let Some(place) = answer.out.get_mut(4..8) {
            place.copy_from_slice(&(-errno).to_ne_bytes());
        }
        answer.done()
    }

    /// A number of 16 bits.
    pub fn u16(mut self, value: u16) -> Self {
        self.out.extend_from_slice(&value.to_ne_bytes());
        self
    }

    /// A number of 32 bits.
    pub fn u32(mut self, value: u32) -> Self {
        self.out.extend_from_slice(&value.to_ne_bytes());
        self
    }

    /// A number of 64 bits.
    pub fn u64(mut self, value: u64) -> Self {
        self.out.extend_from_slice(&value.to_ne_bytes());
        self
    }

    /// These bytes.
    pub fn bytes(mut self, bytes: &[u8]) -> Self {
        self.out.extend_from_slice(bytes);
        self
    }

    /// What a thing is, as the kernel lays it out, after how long it may keep it.
    pub fn attributes(self, number: u64, node: &ViewNode, uid: u32, gid: u32) -> Self {
        let (mode, size, links) = match node {
            ViewNode::Folder(_) => (Self::FOLDER, 0, 2),
            ViewNode::File { size, .. } => (Self::FILE, *size, 1),
            ViewNode::Link(target) => (Self::LINK, target.len() as u64, 1),
        };
        self.u64(number)
            .u64(size)
            .u64(size.div_ceil(512))
            // The three moments and their nanoseconds: a file here has no time of its own, and a program that compares them finds it unchanged.
            .u64(0)
            .u64(0)
            .u64(0)
            .u32(0)
            .u32(0)
            .u32(0)
            .u32(mode)
            .u32(links)
            .u32(uid)
            .u32(gid)
            .u32(0)
            .u32(Self::BLOCK)
            .u32(0)
    }

    /// A name's answer: its number and what it is.
    pub fn entry(self, number: u64, node: &ViewNode, uid: u32, gid: u32) -> Self {
        self.u64(number).u64(0).u64(Self::VALID_SEC).u64(Self::VALID_SEC).u32(0).u32(0).attributes(number, node, uid, gid)
    }

    /// What a thing is, alone.
    pub fn about(self, number: u64, node: &ViewNode, uid: u32, gid: u32) -> Self {
        self.u64(Self::VALID_SEC).u32(0).u32(0).attributes(number, node, uid, gid)
    }

    /// One name of a folder's listing, its length rounded up as the kernel reads them. `at` is where the listing goes on after it.
    pub fn listed(self, number: u64, at: u64, name: &str, node: Option<&ViewNode>) -> Self {
        let kind = match node {
            Some(ViewNode::File { .. }) => 8,
            Some(ViewNode::Link(_)) => 10,
            _ => 4,
        };
        let pad = name.len().next_multiple_of(8) - name.len();
        self.u64(number).u64(at).u32(name.len() as u32).u32(kind).bytes(name.as_bytes()).bytes(&vec![0u8; pad])
    }

    /// Bytes one listed name takes.
    pub fn listed_size(name: &str) -> usize {
        24 + name.len().next_multiple_of(8)
    }

    /// The answer's bytes, its length written in.
    pub fn done(mut self) -> Vec<u8> {
        let length = self.out.len() as u32;
        if let Some(place) = self.out.get_mut(..4) {
            place.copy_from_slice(&length.to_ne_bytes());
        }
        self.out
    }
}
