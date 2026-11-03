//! What only the C library can say: this thread's processor time, the local time of a moment, and a lock shared with other processes.
//!
//! The one crate with `unsafe` code (`scripts/check_rust_contract.py` holds it here): the standard library has
//! no per-thread clock and no time zones. Each call fills a value this function owns and checks the answer.
#![allow(unsafe_code)]

pub mod clock;
mod moment_words;

/// What the C library's allocator holds of the memory given back to it.
pub struct Allocator;

impl Allocator {
    /// Hands the free pages of every arena to the system. glibc keeps what a thread's busiest moment took, and a program of a thread to a connection has many such moments: 1.1 GB stayed on the NAS (2026-11-02) after the work was done.
    pub fn give_back() {
        // SAFETY: no pointer passes, and the call only returns pages nothing uses.
        #[cfg(target_env = "gnu")]
        unsafe {
            libc::malloc_trim(0);
        }
    }
}

/// The processor time of the calling thread.
pub struct ThreadCpu;

impl ThreadCpu {
    /// Seconds of processor time this thread has spent, or `None` when the system does not say.
    pub fn seconds() -> Option<f64> {
        let mut spent = libc::timespec { tv_sec: 0, tv_nsec: 0 };
        // SAFETY: `spent` is a valid timespec owned by this frame, and the call only writes into it.
        let answer = unsafe { libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID, &raw mut spent) };
        (answer == 0).then(|| spent.tv_sec as f64 + spent.tv_nsec as f64 / 1e9)
    }
}

/// This machine's name, as the kernel says it right now.
pub struct Host;

impl Host {
    /// The whole name; "" when the system does not say.
    pub fn name() -> String {
        let mut name = [0u8; 256];
        // SAFETY: the buffer is owned by this frame and its length is passed, one byte short so that the name always ends.
        let answer = unsafe { libc::gethostname(name.as_mut_ptr().cast(), name.len() - 1) };
        if answer != 0 {
            return String::new();
        }
        let end = name.iter().position(|byte| *byte == 0).unwrap_or(name.len());
        String::from_utf8_lossy(name.get(..end).unwrap_or_default()).into_owned()
    }

    /// The short name: `socket.gethostname().split(".")[0].strip()`.
    pub fn short_name() -> String {
        Self::name().split('.').next().map_or_else(String::new, |name| name.trim().to_string())
    }
}

/// Waiting on two sockets at once: a relay reads whichever speaks first.
pub struct Readiness;

impl Readiness {
    /// Whether each has something to read, after at most `timeout`.
    pub fn of_two<A: std::os::fd::AsRawFd, B: std::os::fd::AsRawFd>(
        first: &A,
        second: &B,
        timeout: std::time::Duration,
    ) -> std::io::Result<(bool, bool)> {
        let wanted = libc::POLLIN | libc::POLLHUP | libc::POLLERR;
        let mut fds = [
            libc::pollfd { fd: first.as_raw_fd(), events: libc::POLLIN, revents: 0 },
            libc::pollfd { fd: second.as_raw_fd(), events: libc::POLLIN, revents: 0 },
        ];
        let millis = libc::c_int::try_from(timeout.as_millis()).unwrap_or(libc::c_int::MAX);
        // SAFETY: the array is owned by this frame, and its length is passed.
        let answer = unsafe { libc::poll(fds.as_mut_ptr(), 2, millis) };
        if answer < 0 {
            let error = std::io::Error::last_os_error();
            return if error.kind() == std::io::ErrorKind::Interrupted { Ok((false, false)) } else { Err(error) };
        }
        let [one, other] = fds;
        Ok((one.revents & wanted != 0, other.revents & wanted != 0))
    }
}

/// How many processors, and how busy.
pub struct Cpu;

impl Cpu {
    /// The processors online: `os.cpu_count()`; 1 when the system does not say.
    pub fn count() -> usize {
        // SAFETY: `sysconf` takes a constant and returns a number.
        let answer = unsafe { libc::sysconf(libc::_SC_NPROCESSORS_ONLN) };
        usize::try_from(answer).ok().filter(|count| *count > 0).unwrap_or(1)
    }

    /// The processors this process may use: on a core-pinned VM its slice, not the host's total.
    pub fn available() -> usize {
        std::thread::available_parallelism().map_or_else(|_| Self::count(), std::num::NonZero::get)
    }

    /// The clock ticks of a second, as `/proc` counts in them.
    pub fn clock_ticks() -> Option<i64> {
        // SAFETY: `sysconf` takes a constant and returns a number.
        let answer = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
        Some(answer).filter(|ticks| *ticks > 0)
    }

    /// The load average of the last minute.
    pub fn load_1min() -> Option<f64> {
        Self::load_average().map(|[one, _, _]| one)
    }

    /// The load averages of the last one, five and fifteen minutes.
    pub fn load_average() -> Option<[f64; 3]> {
        let mut load = [0f64; 3];
        // SAFETY: the array is owned by this frame and its length is passed.
        let answer = unsafe { libc::getloadavg(load.as_mut_ptr(), 3) };
        (answer == 3).then_some(load)
    }
}

/// The kernel's memory of a file's pages.
pub struct PageCache;

impl PageCache {
    /// Whether this system can be told to let go of a file's pages.
    pub fn can_drop() -> bool {
        cfg!(target_os = "linux")
    }

    /// Lets go of the clean pages of `file` in this range. Where the system has no such call, nothing is asked and nothing fails.
    pub fn drop_range(file: &std::fs::File, start: u64, length: u64) -> std::io::Result<()> {
        #[cfg(target_os = "linux")]
        {
            use std::os::fd::AsRawFd;
            let start = libc::off_t::try_from(start).map_err(std::io::Error::other)?;
            let length = libc::off_t::try_from(length).map_err(std::io::Error::other)?;
            // SAFETY: the descriptor is the open file's, the call takes numbers and writes nothing.
            let answer = unsafe { libc::posix_fadvise(file.as_raw_fd(), start, length, libc::POSIX_FADV_DONTNEED) };
            if answer != 0 {
                return Err(std::io::Error::from_raw_os_error(answer));
            }
        }
        #[cfg(not(target_os = "linux"))]
        let _nothing_asked = (file, start, length);
        Ok(())
    }
}

/// What the system says of this program's user and kernel.
pub struct Account;

impl Account {
    /// The user this program runs as.
    pub fn uid() -> u32 {
        // SAFETY: the call takes nothing and cannot fail.
        unsafe { libc::getuid() }
    }

    /// `os.uname().release`; "" when the system does not say.
    pub fn kernel_release() -> String {
        // SAFETY: an all-zero `utsname` is a valid value of a plain C struct of byte arrays.
        let mut names: libc::utsname = unsafe { std::mem::zeroed() };
        // SAFETY: the pointer is to a value owned by this frame; the call keeps nothing.
        if unsafe { libc::uname(&raw mut names) } != 0 {
            return String::new();
        }
        let letters: Vec<u8> = names.release.iter().take_while(|letter| **letter != 0).map(|letter| *letter as u8).collect();
        String::from_utf8_lossy(&letters).into_owned()
    }
}

/// A child that outlives this program's session.
pub struct Detached;

impl Detached {
    /// The command starts in a session of its own: a restart of this program leaves it running.
    pub fn in_own_session(command: &mut std::process::Command) {
        use std::os::unix::process::CommandExt;
        // SAFETY: `setsid` is async-signal-safe, and the closure touches nothing else between fork and exec.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }

    /// Whether this child of ours has exited, reaped here: one left alone lingers as a zombie that signal 0 still finds.
    pub fn exited(pid: i64) -> bool {
        let Ok(pid) = libc::pid_t::try_from(pid) else {
            return false;
        };
        // SAFETY: a null status pointer is allowed, and WNOHANG returns at once.
        unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) == pid }
    }
}

/// A folder mounted through FUSE: the connection to the kernel, and who takes the mount off. `fusermount3` is the one program that may mount for a user: it opens `/dev/fuse`, mounts, and passes the open file
/// back over a socket.
pub struct FuseLink {
    /// The connection: the kernel's questions are read from it, and answered on it.
    pub device: std::fs::File,
    /// Waits for this process's end, however it ends, and takes the mount off: a folder whose program is gone answers every look with an error. `fusermount3`'s own `auto_unmount` leaves it standing
    /// (seen on 3.14, 2026-11-03).
    watcher: std::process::Child,
}

impl FuseLink {
    /// Whether this machine can do it: the device, and the helper that mounts.
    pub fn available() -> bool {
        std::path::Path::new("/dev/fuse").exists()
            && std::process::Command::new("fusermount3").arg("-V").output().is_ok_and(|done| done.status.success())
    }

    /// Lets go of a mount of `folder`, one whose program is gone too. Nothing mounted there is no failure anyone needs to hear of.
    pub fn unmount(folder: &std::path::Path) {
        // absent-ok: no helper means nothing was mounted by it.
        drop(std::process::Command::new("fusermount3").args(["-u", "-z", "--"]).arg(folder).output());
    }

    /// Mounts `folder` read-only under `name`: the link, or the helper's words.
    #[cfg(target_os = "linux")]
    pub fn mount(folder: &std::path::Path, name: &str) -> Result<Self, String> {
        use std::os::fd::AsRawFd;
        use std::os::unix::process::CommandExt;
        use std::process::{Command, Stdio};
        let (ours, theirs) = std::os::unix::net::UnixStream::pair().map_err(|error| error.to_string())?;
        let passed = theirs.as_raw_fd();
        // SAFETY: the descriptor is this frame's, and the call clears its close-on-exec flag alone: the helper reads its number from `_FUSE_COMMFD`.
        if unsafe { libc::fcntl(passed, libc::F_SETFD, 0) } != 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let helper = Command::new("fusermount3")
            .arg("-o")
            .arg(format!("ro,nosuid,nodev,fsname={name},subtype=caravan"))
            .arg("--")
            .arg(folder)
            .env("_FUSE_COMMFD", passed.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .output()
            .map_err(|error| format!("fusermount3: {error}"))?;
        drop(theirs);
        let Some(device) = Self::received(&ours).map_err(|error| error.to_string())? else {
            return Err(String::from_utf8_lossy(&helper.stderr).trim().to_string());
        };
        // Its input is held by this process alone, and ends with it. In a group of its own: what stops this process's group is not to stop it.
        let watcher = Command::new("sh")
            .arg("-c")
            .arg("cat >/dev/null; exec fusermount3 -u -z -- \"$0\"")
            .arg(folder)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .process_group(0)
            .spawn()
            .map_err(|error| format!("sh: {error}"))?;
        Ok(Self { device, watcher })
    }

    /// The parts for whoever answers the mount: the connection, and what is to live as long as the answering does.
    pub fn parts(self) -> (std::fs::File, std::process::Child) {
        (self.device, self.watcher)
    }

    /// No such thing off Linux: this scout's release runs on Linux, and a build for another system says so.
    #[cfg(not(target_os = "linux"))]
    pub fn mount(_folder: &std::path::Path, _name: &str) -> Result<Self, String> {
        Err("FUSE is read on Linux only".to_string())
    }

    /// The file the helper passed, `None` when it passed nothing: it failed, and its words are elsewhere.
    #[cfg(target_os = "linux")]
    fn received(socket: &std::os::unix::net::UnixStream) -> std::io::Result<Option<std::fs::File>> {
        use std::os::fd::{AsRawFd, FromRawFd};
        let mut byte = [0u8; 1];
        let mut place = libc::iovec { iov_base: byte.as_mut_ptr().cast(), iov_len: byte.len() };
        // Room for the control message of one descriptor, aligned as one must be.
        let mut control = [0u64; 8];
        // SAFETY: an all-zero `msghdr` is a valid value of a plain C struct.
        let mut message: libc::msghdr = unsafe { std::mem::zeroed() };
        message.msg_iov = &raw mut place;
        message.msg_iovlen = 1;
        message.msg_control = control.as_mut_ptr().cast();
        // The field's width is the C library's: `as` says the same on all of them.
        message.msg_controllen = std::mem::size_of_val(&control) as _;
        // SAFETY: every pointer in `message` is to a value of this frame, and the call keeps none of them.
        if unsafe { libc::recvmsg(socket.as_raw_fd(), &raw mut message, libc::MSG_CMSG_CLOEXEC) } < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: the call above filled `message`.
        let header = unsafe { libc::CMSG_FIRSTHDR(&raw const message) };
        if header.is_null() {
            return Ok(None);
        }
        // SAFETY: the header is not null, and lies in `control`.
        let (level, kind) = unsafe { ((*header).cmsg_level, (*header).cmsg_type) };
        if level != libc::SOL_SOCKET || kind != libc::SCM_RIGHTS {
            return Ok(None);
        }
        // SAFETY: a message of SCM_RIGHTS carries descriptors, and its data need not be aligned for one.
        let descriptor = unsafe { std::ptr::read_unaligned(libc::CMSG_DATA(header).cast::<libc::c_int>()) };
        // SAFETY: the kernel made this descriptor for this process just now, and nothing else owns it.
        Ok(Some(unsafe { std::fs::File::from_raw_fd(descriptor) }))
    }
}

/// The disk a path lives on.
pub struct Disk;

impl Disk {
    /// `os.access(path, os.W_OK)`: whether this process may write there.
    pub fn writable(path: &std::path::Path) -> bool {
        use std::os::unix::ffi::OsStrExt;
        let Ok(text) = std::ffi::CString::new(path.as_os_str().as_bytes()) else {
            return false;
        };
        // SAFETY: the pointer is to a string owned by this frame; access keeps nothing.
        unsafe { libc::access(text.as_ptr(), libc::W_OK) == 0 }
    }

    /// (its size, what is free for this user), in bytes, as `shutil.disk_usage` says them; `None` when the system will not say.
    pub fn usage(path: &std::path::Path) -> Option<(u64, u64)> {
        use std::os::unix::ffi::OsStrExt;
        let name = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
        // SAFETY: an all-zero `statvfs` is a valid value of a plain C struct of integers.
        let mut figures: libc::statvfs = unsafe { std::mem::zeroed() };
        // SAFETY: both pointers are to values owned by this frame; the call keeps neither.
        let answer = unsafe { libc::statvfs(name.as_ptr(), &raw mut figures) };
        if answer != 0 {
            return None;
        }
        // The fields' width is the system's: `as` says the same on all of them.
        let unit = figures.f_frsize as u64;
        Some((figures.f_blocks as u64 * unit, figures.f_bavail as u64 * unit))
    }

    /// Whether the disk `path` lies on spins — an HDD — as Linux says it in `/sys`; `None` where it does not say: another system, a network share, a FUSE mount, a file system of no block device.
    pub fn rotational(path: &std::path::Path) -> Option<bool> {
        use std::os::unix::fs::MetadataExt;
        let (major, minor) = Self::device_numbers(std::fs::metadata(path).ok()?.dev());
        let device = std::fs::canonicalize(format!("/sys/dev/block/{major}:{minor}")).ok()?;
        let read = |folder: &std::path::Path| std::fs::read_to_string(folder.join("queue/rotational")).ok();
        // A partition says nothing of itself: the disk it is a part of does.
        let said = read(&device).or_else(|| device.parent().and_then(read))?;
        match said.trim() {
            "1" => Some(true),
            "0" => Some(false),
            _ => None,
        }
    }

    /// (major, minor) of a device number, split as glibc's `major` and `minor` split it.
    pub fn device_numbers(dev: u64) -> (u64, u64) {
        ((dev >> 8) & 0xfff | (dev >> 32) & 0xffff_f000, dev & 0xff | (dev >> 12) & 0xffff_ff00)
    }
}

/// Signals to a process.
pub struct Signals;

impl Signals {
    /// The name of a signal: what "exited (code -11)" hides.
    pub fn name(number: i32) -> Option<&'static str> {
        const NAMES: [(i32, &str); 15] = [
            (libc::SIGHUP, "SIGHUP"),
            (libc::SIGINT, "SIGINT"),
            (libc::SIGQUIT, "SIGQUIT"),
            (libc::SIGILL, "SIGILL"),
            (libc::SIGTRAP, "SIGTRAP"),
            (libc::SIGABRT, "SIGABRT"),
            (libc::SIGBUS, "SIGBUS"),
            (libc::SIGFPE, "SIGFPE"),
            (libc::SIGKILL, "SIGKILL"),
            (libc::SIGUSR1, "SIGUSR1"),
            (libc::SIGSEGV, "SIGSEGV"),
            (libc::SIGUSR2, "SIGUSR2"),
            (libc::SIGPIPE, "SIGPIPE"),
            (libc::SIGALRM, "SIGALRM"),
            (libc::SIGTERM, "SIGTERM"),
        ];
        NAMES.iter().find(|(said, _)| *said == number).map(|(_, name)| *name)
    }

    /// The number of the signal no process can catch.
    pub const KILL: i32 = libc::SIGKILL;

    /// Whether a process runs: a signal of nothing tells. One that is another user's still runs.
    pub fn alive(pid: i64) -> bool {
        let Ok(pid) = libc::pid_t::try_from(pid) else {
            return false;
        };
        // SAFETY: signal 0 only asks; the call takes two numbers.
        let answer = unsafe { libc::kill(pid, 0) };
        answer == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
    }

    /// Asks a process to end: SIGTERM.
    pub fn terminate(pid: i64) -> std::io::Result<()> {
        Self::send(pid, libc::SIGTERM)
    }

    /// Ends a process: SIGKILL.
    pub fn kill(pid: i64) -> std::io::Result<()> {
        Self::send(pid, libc::SIGKILL)
    }

    fn send(pid: i64, signal: libc::c_int) -> std::io::Result<()> {
        let pid = libc::pid_t::try_from(pid).map_err(std::io::Error::other)?;
        // SAFETY: the call takes two numbers.
        let answer = unsafe { libc::kill(pid, signal) };
        if answer == 0 { Ok(()) } else { Err(std::io::Error::last_os_error()) }
    }
}

/// A lock on a file (`flock`), so that two processes wait for each other. Dropped, it is let go.
#[derive(Debug)]
pub struct FileLock {
    file: std::fs::File,
}

impl FileLock {
    /// Waits for the lock on `path`, making the file when there is none.
    pub fn exclusive(path: &std::path::Path) -> std::io::Result<Self> {
        if let Some(folder) = path.parent() {
            std::fs::create_dir_all(folder)?;
        }
        let file = std::fs::OpenOptions::new().append(true).create(true).open(path)?;
        loop {
            // SAFETY: the descriptor belongs to `file`, alive for the call; flock touches no memory of this process.
            let answer = unsafe { libc::flock(std::os::fd::AsRawFd::as_raw_fd(&file), libc::LOCK_EX) };
            if answer == 0 {
                return Ok(Self { file });
            }
            let error = std::io::Error::last_os_error();
            if error.kind() != std::io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        // SAFETY: the descriptor belongs to `self.file`, alive for the call. A failed unlock changes nothing: closing the file lets go too.
        unsafe { libc::flock(std::os::fd::AsRawFd::as_raw_fd(&self.file), libc::LOCK_UN) };
    }
}

/// A moment on the local clock of the time zone `TZ` names.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LocalTime {
    /// The year.
    pub year: i32,
    /// The month, 1 to 12.
    pub month: u32,
    /// The day of the month.
    pub day: u32,
    /// The hour.
    pub hour: u32,
    /// The minute.
    pub minute: u32,
    /// The second.
    pub second: u32,
    /// The day of the week, Monday being 0.
    pub weekday: u32,
    /// The zone's offset from UTC at this moment, in minutes.
    pub offset_minutes: i64,
}

impl LocalTime {
    fn parts_of(epoch: i64) -> Option<libc::tm> {
        let moment: libc::time_t = epoch;
        // SAFETY: an all-zero `tm` is a valid value of a plain C struct of integers and a pointer never read here.
        let mut parts: libc::tm = unsafe { std::mem::zeroed() };
        // SAFETY: both pointers are to values owned by this frame; localtime_r keeps neither.
        let answer = unsafe { libc::localtime_r(&raw const moment, &raw mut parts) };
        (!answer.is_null()).then_some(parts)
    }

    /// The epoch of `minute` minutes after Monday 00:00 of the week `epoch` stands in, on the zone's clock. Wall-clock arithmetic: the C
    /// library carries the minutes over the days, and over a clock's change.
    pub fn epoch_of_week_minute(epoch: i64, minute: i64) -> Option<i64> {
        let mut parts = Self::parts_of(epoch)?;
        parts.tm_mday -= (parts.tm_wday + 6) % 7;
        parts.tm_hour = 0;
        parts.tm_min = i32::try_from(minute).ok()?;
        parts.tm_sec = 0;
        parts.tm_isdst = -1;
        // SAFETY: the pointer is to a value owned by this frame; mktime keeps nothing.
        let answer = unsafe { libc::mktime(&raw mut parts) };
        (answer != -1).then_some(answer)
    }

    /// `epoch` seconds on the local clock; `None` when the system cannot place them.
    pub fn of(epoch: i64) -> Option<Self> {
        let parts = Self::parts_of(epoch)?;
        Some(Self {
            year: parts.tm_year + 1900,
            month: u32::try_from(parts.tm_mon + 1).ok()?,
            day: u32::try_from(parts.tm_mday).ok()?,
            hour: u32::try_from(parts.tm_hour).ok()?,
            minute: u32::try_from(parts.tm_min).ok()?,
            second: u32::try_from(parts.tm_sec).ok()?,
            weekday: u32::try_from((parts.tm_wday + 6) % 7).ok()?,
            offset_minutes: parts.tm_gmtoff / 60,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_device_number_splits_as_the_system_makes_it() {
        // glibc's `makedev`: the low twelve bits of the major and eight of the minor in the low word, the rest above.
        let made = |major: u64, minor: u64| (major & 0xfff) << 8 | (major & !0xfff) << 32 | minor & 0xff | (minor & !0xff) << 12;
        assert_eq!(made(8, 2), 0x802, "sda2, as `stat` says it");
        for (major, minor) in [(8, 2), (259, 2), (253, 0), (0x1234, 0x5_6789), (4095, 255), (4096, 256)] {
            assert_eq!(Disk::device_numbers(made(major, minor)), (major, minor), "{major}:{minor}");
        }
    }

    #[test]
    fn a_disk_that_does_not_say_whether_it_spins_says_nothing() {
        assert_eq!(Disk::rotational(std::path::Path::new("/no/such/folder")), None);
    }

    #[test]
    fn a_thread_that_works_spends_processor_time() {
        let before = ThreadCpu::seconds().unwrap();
        let mut sum = 0u64;
        for at in 0..3_000_000u64 {
            sum = sum.wrapping_add(at.wrapping_mul(at));
        }
        std::hint::black_box(sum);
        let spent = ThreadCpu::seconds().unwrap() - before;
        assert!(spent > 0.0 && spent < 30.0, "{spent} seconds for a short loop");
    }

    #[test]
    fn the_words_of_a_moment_read_as_python_writes_them() {
        let moment = LocalTime { year: 2026, month: 3, day: 9, hour: 7, minute: 5, second: 2, weekday: 0, offset_minutes: 240 };
        assert_eq!(moment.date(), "2026-03-09");
        assert_eq!(moment.iso(), "2026-03-09T07:05:02");
    }

    #[test]
    fn a_moment_is_placed_on_some_local_clock() {
        // The middle of a month and of a day: the same month and year on every clock on Earth.
        let moment = LocalTime::of(1_781_524_800).unwrap();
        assert_eq!((moment.year, moment.month), (2026, 6));
        assert!((14..=16).contains(&moment.day), "{moment:?}");
        assert!(moment.hour < 24 && moment.minute < 60 && moment.second < 60, "{moment:?}");
    }

    #[test]
    fn a_week_s_minute_lands_on_its_own_clock() {
        let now = 1_793_000_000;
        let here = LocalTime::of(now).unwrap();
        let minute = i64::from(here.weekday) * 1440 + i64::from(here.hour) * 60 + i64::from(here.minute);
        let back = LocalTime::epoch_of_week_minute(now, minute).unwrap();
        assert_eq!(back, now - i64::from(here.second));
        let monday = LocalTime::of(LocalTime::epoch_of_week_minute(now, 0).unwrap()).unwrap();
        assert_eq!((monday.weekday, monday.hour, monday.minute), (0, 0, 0));
        let next = LocalTime::of(LocalTime::epoch_of_week_minute(now, 7 * 1440 + 90).unwrap()).unwrap();
        assert_eq!((next.weekday, next.hour, next.minute), (0, 1, 30));
    }

    #[test]
    fn a_lock_waits_for_the_one_who_holds_it() {
        let path = std::env::temp_dir().join(format!("caravan-lock-{}", std::process::id()));
        let held = FileLock::exclusive(&path).unwrap();
        let (told, heard) = std::sync::mpsc::channel();
        let second = path.clone();
        let waiting = std::thread::spawn(move || {
            let lock = FileLock::exclusive(&second).unwrap();
            told.send(()).unwrap();
            drop(lock);
        });
        assert!(heard.recv_timeout(std::time::Duration::from_millis(100)).is_err(), "it is held");
        drop(held);
        assert!(heard.recv_timeout(std::time::Duration::from_secs(5)).is_ok(), "let go, it is the other's");
        waiting.join().unwrap();
        std::fs::remove_file(&path).unwrap();
    }
}
