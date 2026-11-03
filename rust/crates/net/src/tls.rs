//! The roots a provider's certificate is checked against, and a socket turned into a TLS connection.

use crate::stream::Stream;
use rustls::pki_types::pem::PemObject;
use rustls::pki_types::{CertificateDer, ServerName};
use rustls::{ClientConfig, ClientConnection, RootCertStore, StreamOwned};
use std::io;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Why no TLS could be set up. The words go to the journal; a client is told the caravan's own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TlsError(pub String);

/// The certificates this machine trusts, as a TLS client's settings.
#[derive(Debug, Clone)]
pub struct TrustedRoots {
    config: Arc<ClientConfig>,
    said: String,
}

impl TrustedRoots {
    /// Where a system keeps them: Debian's file, Red Hat's, macOS's.
    const SYSTEM_FILES: [&'static str; 3] =
        ["/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem"];

    /// The roots of `file` when it is given (`SSL_CERT_FILE`, as OpenSSL reads it), else of the system's own file. No file that gives one is
    /// an error: a provider's certificate is never taken unchecked.
    pub fn read(file: Option<PathBuf>) -> Result<Self, TlsError> {
        let candidates: Vec<PathBuf> = match file {
            Some(file) => vec![file],
            None => Self::SYSTEM_FILES.iter().map(PathBuf::from).collect(),
        };
        let mut roots = RootCertStore::empty();
        for path in candidates.iter().filter(|path| path.exists()) {
            Self::add_file(&mut roots, path)?;
            if !roots.is_empty() {
                let said = format!("{} trusted certificates from {}", roots.len(), path.display());
                return Self::of(roots, said);
            }
        }
        Err(TlsError(format!("no trusted certificates in {candidates:?}")))
    }

    /// What was found and where, for the words of a start.
    pub fn said(&self) -> &str {
        &self.said
    }

    fn add_file(roots: &mut RootCertStore, path: &Path) -> Result<(), TlsError> {
        let certificates =
            CertificateDer::pem_file_iter(path).map_err(|error| TlsError(format!("{}: {error}", path.display())))?;
        // A certificate of a file that does not parse is no reason to refuse the rest of the file: system bundles hold odd ones.
        roots.add_parsable_certificates(certificates.flatten());
        Ok(())
    }

    fn of(roots: RootCertStore, said: String) -> Result<Self, TlsError> {
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let config = ClientConfig::builder_with_provider(provider)
            .with_safe_default_protocol_versions()
            .map_err(|error| TlsError(error.to_string()))?
            .with_root_certificates(roots)
            .with_no_client_auth();
        Ok(Self { config: Arc::new(config), said })
    }

    /// `socket` as a TLS connection to `host`, its handshake done. `look_around` runs each time a read of the handshake has waited its turn:
    /// it says whether to go on.
    pub fn wrap<E: From<io::Error>>(
        &self,
        mut socket: TcpStream,
        host: &str,
        look_around: &mut dyn FnMut() -> Result<(), E>,
    ) -> Result<Stream, E> {
        let name = ServerName::try_from(host.to_string()).map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
        let mut connection = ClientConnection::new(Arc::clone(&self.config), name).map_err(io::Error::other)?;
        while connection.is_handshaking() {
            match connection.complete_io(&mut socket) {
                Ok(_) => {}
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut) => look_around()?,
                Err(error) => return Err(error.into()),
            }
        }
        Ok(Stream::Tls(Box::new(StreamOwned::new(connection, socket))))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::time::Duration;

    /// A certificate that stands for any: only that it parses is read here. Its key was thrown away when it was made.
    const CERTIFICATE: &str = "\
-----BEGIN CERTIFICATE-----
MIIBljCCATugAwIBAgIUeTzzjLmrt+ETNl9IErdqoo6XZcswCgYIKoZIzj0EAwIw
HzEdMBsGA1UEAwwUdGhlIG5ldCBjcmF0ZSdzIHRlc3QwIBcNMjYxMTAxMTU1NTA0
WhgPMjEyNjEwMDgxNTU1MDRaMB8xHTAbBgNVBAMMFHRoZSBuZXQgY3JhdGUncyB0
ZXN0MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEonn2HGWtLtPmQVgvuqEhLF7G
phzqeIUY2rMp8VYI5mk1zu24sYyGPro9i2ze2b+OdzpbhP5NrDqS30GzSlXvJKNT
MFEwHQYDVR0OBBYEFDicGcrOG5Wye6Otdzgzr2ePj6IHMB8GA1UdIwQYMBaAFDic
GcrOG5Wye6Otdzgzr2ePj6IHMA8GA1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwID
SQAwRgIhAN/c4js+ZIWtsZ82H7LmUe5ncOERG5ZRE/95C5Z1sHkbAiEA0XyRE8Al
qM1PX3AMklJo3IIKhJiITyp5Nou1pcTkeQA=
-----END CERTIFICATE-----
";

    fn file_with(name: &str, text: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("caravan-net-{}-{name}", std::process::id()));
        std::fs::write(&path, text).unwrap();
        path
    }

    /// The roots of a file of `name`'s own: tests run side by side, and a file written while another reads it holds nothing yet.
    fn roots(name: &str) -> TrustedRoots {
        TrustedRoots::read(Some(file_with(name, CERTIFICATE))).unwrap()
    }

    #[test]
    fn a_file_with_a_certificate_says_how_many_and_where() {
        let path = file_with("one.pem", CERTIFICATE);
        let found = TrustedRoots::read(Some(path.clone())).unwrap();
        assert_eq!(found.said(), format!("1 trusted certificates from {}", path.display()));
    }

    #[test]
    fn a_file_that_holds_none_is_no_trust() {
        let empty = file_with("empty.pem", "no certificate in here");
        let said = TrustedRoots::read(Some(empty.clone())).unwrap_err();
        assert!(said.0.contains(&empty.display().to_string()), "{said:?}");
        let gone = std::env::temp_dir().join("caravan-net-no-such-file");
        assert!(TrustedRoots::read(Some(gone)).is_err());
    }

    /// A socket to a listener that accepted it, and the other end.
    fn pair() -> (TcpStream, TcpStream) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        (near, far)
    }

    #[test]
    fn a_provider_that_keeps_silent_gives_the_caller_its_turn_each_wait() {
        let (near, _far) = pair();
        near.set_read_timeout(Some(Duration::from_millis(20))).unwrap();
        let mut turns = 0;
        let said = roots("silent.pem").wrap::<io::Error>(near, "localhost", &mut || {
            turns += 1;
            if turns < 2 { Ok(()) } else { Err(io::Error::other("enough")) }
        });
        assert_eq!(said.unwrap_err().to_string(), "enough");
        assert_eq!(turns, 2);
    }

    #[test]
    fn a_provider_that_closes_at_once_is_a_failure_and_no_wait() {
        let (near, far) = pair();
        drop(far);
        let mut turns = 0;
        let said = roots("closes.pem").wrap::<io::Error>(near, "localhost", &mut || {
            turns += 1;
            Ok(())
        });
        assert!(said.is_err());
        assert_eq!(turns, 0);
    }

    #[test]
    fn a_name_that_is_no_name_is_refused_before_anything_is_sent() {
        let (near, _far) = pair();
        let said = roots("no-name.pem").wrap::<io::Error>(near, "not a name!", &mut || Ok(()));
        assert_eq!(said.unwrap_err().kind(), io::ErrorKind::InvalidInput);
    }
}
