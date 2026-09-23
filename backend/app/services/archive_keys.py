"""The backup key (v0.30.0): an age X25519 identity that encrypts every
archive Cabinet writes and keys the MAC that proves Cabinet wrote it.

- **Where it comes from.** `BACKUP_KEY_FILE` (a Docker secret) when set,
  never modified by Cabinet; or `BACKUP_KEY` (the same text as a variable,
  commas or newlines between identities), written at every start to a
  container-local file for `age`; otherwise `backup.key` on the state
  volume, generated at first start (0600). Each holds one identity a line
  (`AGE-SECRET-KEY-1...`, `#` comments allowed); the first encrypts, and an
  archive is verified with the identity its `mac_recipient` names, so older
  archives stay readable after a rotation while their identity is kept.
- **The MAC.** age authenticates an archive's contents, but anyone who knows
  the public recipient can make a new one. So the manifest carries
  `mac_recipient` and `mac`: HMAC-SHA256, keyed by HKDF-SHA256 over that
  identity's raw 32-byte X25519 secret (empty salt, info
  `cabinet-backup-mac-v1`), over the canonical manifest (without `mac`)
  followed by `SHA256SUMS`. Only the private key can forge one.
- **Where it lives.** A generated key is only as private as the state
  volume; `location()` says whether that shares storage with the backups.

The key is never sent over the API: `python -m app.cli backup-key show`
prints it inside the container, the proof of ownership.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import ConfigError, get_settings

logger = logging.getLogger(__name__)

SECRET_HRP = "age-secret-key-"
RECIPIENT_HRP = "age"
MAC_INFO = b"cabinet-backup-mac-v1"
GENERATED_NAME = "backup.key"

# --- bech32 (BIP 173), as age uses it for keys --------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _polymod(values) -> int:
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= _GEN[i] if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data, frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = bits = 0
    out = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad and bits:
        out.append((acc << (tobits - bits)) & maxv)
    elif not pad and (bits >= frombits or (acc << (tobits - bits)) & maxv):
        raise ValueError("invalid padding")
    return out


def bech32_encode(hrp: str, payload: bytes) -> str:
    data = _convert(payload, 8, 5, True)
    check = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ 1
    data += [(check >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data)


def bech32_decode(text: str) -> tuple[str, bytes]:
    if text.lower() != text and text.upper() != text:
        raise ValueError("mixed case")
    text = text.lower()
    pos = text.rfind("1")
    if pos < 1 or len(text) - pos < 7:
        raise ValueError("no separator")
    hrp, rest = text[:pos], text[pos + 1 :]
    try:
        data = [_CHARSET.index(c) for c in rest]
    except ValueError:
        raise ValueError("bad character") from None
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise ValueError("bad checksum")
    return hrp, bytes(_convert(data[:-6], 5, 8, False))


# --- identities -----------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    secret: bytes  # the raw 32-byte X25519 secret
    recipient: str  # age1...

    @property
    def text(self) -> str:
        return bech32_encode(SECRET_HRP, self.secret).upper()


def identity_from_secret(secret: bytes) -> Identity:
    public = (
        X25519PrivateKey.from_private_bytes(secret)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return Identity(secret, bech32_encode(RECIPIENT_HRP, public))


def parse_identity(line: str) -> Identity:
    line = line.strip()
    # age itself only takes the upper-case form; a lower-case key would encrypt
    # (only the public key is needed) and then never decrypt.
    if not line.startswith("AGE-SECRET-KEY-1"):
        raise ValueError("an identity starts AGE-SECRET-KEY-1, in capitals")
    hrp, secret = bech32_decode(line)
    if hrp != SECRET_HRP or len(secret) != 32:
        raise ValueError("not an age X25519 identity")
    return identity_from_secret(secret)


def new_identity() -> Identity:
    raw = X25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return identity_from_secret(raw)


def parse_identities(text: str) -> list[Identity]:
    """Every identity in a key file, first (the one that encrypts) first.
    Raises ValueError naming the line that isn't one; never the value."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            found.append(parse_identity(line))
        except ValueError as exc:
            raise ValueError(f"line {number} is not an age identity ({exc})") from None
    if not found:
        raise ValueError("it holds no age identity (AGE-SECRET-KEY-1...)")
    return found


# --- the key file -----------------------------------------------------------------


def source() -> str:
    """Where the key comes from: `file` (BACKUP_KEY_FILE), `environment`
    (BACKUP_KEY), or `generated` (backup.key on the state volume)."""
    config = get_settings()
    if config.backup_key_file:
        return "file"
    if config.backup_key.strip():
        return "environment"
    return "generated"


def supplied() -> bool:
    """A supplied key, file or variable, is never changed by Cabinet."""
    return source() != "generated"


def parse_environment_key(text: str) -> list[Identity]:
    """BACKUP_KEY: identities separated by newlines or commas, comments
    allowed, the first encrypting."""
    return parse_identities(text.replace(",", "\n"))


RUNTIME_DIR = Path("/run/cabinet")  # inside the container, never a data volume


def _runtime_dir() -> Path:
    """Where an environment-supplied key is written for `age` to read (it
    takes identities only from a file): inside the container, on the node's
    own disk and gone with the container, never the state volume, which may
    be shared storage. Outside the image (tests, a dev machine) a private
    folder in the temp directory stands in."""
    if RUNTIME_DIR.is_dir() and os.access(RUNTIME_DIR, os.W_OK):
        return RUNTIME_DIR
    fallback = Path(tempfile.gettempdir()) / "cabinet-backup-key"
    fallback.mkdir(mode=0o700, parents=True, exist_ok=True)
    return fallback


def state_dir() -> Path:
    return Path(get_settings().secret_key_file).resolve().parent


def key_path() -> Path:
    """The file age reads identities from: BACKUP_KEY_FILE, or the generated
    one on the state volume."""
    config = get_settings()
    where = source()
    if where == "file":
        return Path(config.backup_key_file)
    if where == "environment":
        return _runtime_dir() / GENERATED_NAME
    return state_dir() / GENERATED_NAME


def _fsync_dir(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return  # not possible everywhere (Windows); best effort
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_partial(path: Path, text: str) -> Path:
    """The whole file, synced to disk, beside `path` (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    return partial


def _create_exclusively(path: Path, text: str) -> bool:
    """Write `path` only if it doesn't exist, atomically: a hard link fails
    when the name is taken, so an existing key is never overwritten, even
    when a stat of it failed. True if this call created it."""
    partial = _write_partial(path, text)
    try:
        os.link(partial, path)
    except FileExistsError:
        return False
    finally:
        partial.unlink(missing_ok=True)
    _fsync_dir(path.parent)
    return True


def _replace(path: Path, text: str) -> None:
    """Replace a key file Cabinet owns (a rotated generated key, or the
    runtime copy of BACKUP_KEY), synced."""
    partial = _write_partial(path, text)
    partial.replace(path)
    _fsync_dir(path.parent)


def _key_file_text(identities: list[Identity]) -> str:
    lines = ["# Cabinet backup key. Keep a copy outside Cabinet: without it the"]
    lines.append("# encrypted archives can't be opened by anyone. First line encrypts.")
    for identity in identities:
        lines.append(f"# public key: {identity.recipient}")
        lines.append(identity.text)
    return "\n".join(lines) + "\n"


class KeyUnavailable(RuntimeError):
    """The backup key can't be read right now. Never a reason to make a new
    one: that would strand every archive made with the old."""


def _read_key(path: Path) -> list[Identity]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise KeyUnavailable(
            f"The backup key {path} is missing. Put your saved copy back, or supply it "
            "as BACKUP_KEY_FILE; Cabinet makes a new key only on a first start."
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise KeyUnavailable(
            f"The backup key {path} cannot be read ({type(exc).__name__})."
        ) from None
    try:
        return parse_identities(text)
    except ValueError as exc:
        raise KeyUnavailable(f"The backup key {path} can't be used: {exc}") from None


def ensure_key() -> list[Identity]:
    """At startup only: load the backup key, generating it when none is
    supplied and none exists yet. A supplied key that can't be read or
    parsed is a ConfigError naming BACKUP_KEY_FILE, so startup stops before
    any backup is written. A generated key is created exclusively, so a key
    already there is never replaced, even if looking for it failed."""
    config = get_settings()
    if config.backup_key_file and config.backup_key.strip():
        raise ConfigError(
            "Set BACKUP_KEY_FILE or BACKUP_KEY, not both: Cabinet can't tell which key you mean."
        )
    path = key_path()
    where = source()
    if where == "environment":
        try:
            found = parse_environment_key(config.backup_key)
        except ValueError as exc:
            raise ConfigError(
                f"BACKUP_KEY: {exc}. Make one with: python -m app.cli backup-key new"
            ) from None
        # Written afresh on every start, inside the container, for age.
        _replace(path, _key_file_text(found))
        return _read_key(path)
    if where == "file":
        try:
            return _read_key(path)
        except KeyUnavailable as exc:
            raise ConfigError(
                f"BACKUP_KEY_FILE: {exc} It must be readable by the app's user; Cabinet "
                "never changes a supplied key file."
            ) from None
    identity = new_identity()
    if _create_exclusively(path, _key_file_text([identity])):
        logger.warning(
            "Generated a backup key (public key %s) in %s. Every backup is encrypted with it: "
            "save a copy outside Cabinet (python -m app.cli backup-key show).",
            identity.recipient,
            path,
        )
    try:
        return _read_key(path)
    except KeyUnavailable as exc:
        raise ConfigError(str(exc)) from None


def identities() -> list[Identity]:
    """The configured identities, read afresh. Never generates: at runtime a
    key that can't be read is KeyUnavailable (the backup fails and alerts)."""
    return _read_key(key_path())


def primary() -> Identity:
    return identities()[0]


def rotate() -> Identity | None:
    """Put a new identity first in the generated key file, keeping the old
    ones so older archives stay readable. Returns it, or None when the key
    is supplied (BACKUP_KEY_FILE or BACKUP_KEY): a supplied key is never
    modified; the operator rotates it."""
    if supplied():
        return None
    current = identities()
    fresh = new_identity()
    _replace(key_path(), _key_file_text([fresh, *current]))
    return fresh


# --- the MAC ------------------------------------------------------------------------


def canonical(manifest: dict) -> bytes:
    """The bytes the MAC covers for a manifest: sorted keys, no spaces,
    UTF-8, with `mac` removed (so `mac_recipient` is covered)."""
    body = {k: v for k, v in manifest.items() if k != "mac"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def mac_key(identity: Identity) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"", info=MAC_INFO).derive(
        identity.secret
    )


def compute_mac(identity: Identity, manifest: dict, sums: bytes) -> str:
    return hmac.new(mac_key(identity), canonical(manifest) + sums, hashlib.sha256).hexdigest()


def sign(manifest: dict, sums: bytes, identity: Identity | None = None) -> dict:
    identity = identity or primary()
    manifest["mac_recipient"] = identity.recipient
    manifest["mac"] = compute_mac(identity, manifest, sums)
    return manifest


class NotOurs(ValueError):
    """The archive was not made with this deployment's backup key."""


def verify(manifest: dict, sums: bytes) -> Identity:
    """Check an archive's MAC with the one configured identity its
    `mac_recipient` names; return that identity."""
    recipient = manifest.get("mac_recipient")
    mac = manifest.get("mac")
    matches = [i for i in identities() if i.recipient == recipient]
    if len(matches) != 1 or not isinstance(mac, str):
        raise NotOurs("This archive was not made with your backup key.")
    if not hmac.compare_digest(compute_mac(matches[0], manifest, sums), mac):
        raise NotOurs("This archive was not made with your backup key.")
    return matches[0]


def mac_digest(manifest: dict) -> bytes:
    """What the archive record keeps to recognise an archive: the SHA-256 of
    its (verified) MAC, never its file name or time."""
    return hashlib.sha256(bytes.fromhex(manifest["mac"])).digest()


# --- where the key lives -------------------------------------------------------------

# "separate" is only ever said for these: local block filesystems, where a
# different device means different storage. Anything else is not_verified.
LOCAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "bcachefs"}
NETWORK_FS = {
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "ceph", "glusterfs", "9p", "afs", "davfs",
    "fuse.sshfs", "fuse.glusterfs", "fuse.rclone", "fuse.s3fs", "lustre", "gpfs",
}  # fmt: skip
MOUNTINFO = Path("/proc/self/mountinfo")


@dataclass(frozen=True)
class Mount:
    mount_id: str
    device: str  # major:minor
    root: str  # the path inside the filesystem that is mounted here
    point: str
    fstype: str
    source: str


def _unescape(field: str) -> str:
    """mountinfo escapes space, tab, newline, and backslash as \\ooo octal;
    everything else, UTF-8 included, is as it is."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def parse_mountinfo(text: str) -> list[Mount]:
    mounts = []
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if not sep or len(fields) < 5 or len(tail) < 2:
            continue
        root, point = _unescape(fields[3]), _unescape(fields[4])
        mounts.append(Mount(fields[0], fields[2], root, point, tail[0], tail[1]))
    return mounts


def _mount_of(path: PurePosixPath, mounts: list[Mount]) -> Mount | None:
    """The mount a path is on: the longest mount point containing it; of two
    at the same point, the later (the one on top)."""
    text = str(path)
    best = None
    for mount in mounts:
        point = mount.point.rstrip("/") or "/"
        contains = point == "/" or text == point or text.startswith(point + "/")
        if contains and (best is None or len(point) >= len(best.point.rstrip("/") or "/")):
            best = mount
    return best


def _inside(path: PurePosixPath, mount: Mount) -> str:
    """Where `path` is within its filesystem: the mount's root plus the rest."""
    rest = str(path)[len(mount.point.rstrip("/")) :]
    return (mount.root.rstrip("/") + "/" + rest.lstrip("/")).rstrip("/") or "/"


def compare_locations(key: Path, backups: Path, mountinfo: str | None) -> str:
    """`separate`, `shared` (the key sits on the storage the backups go to),
    or `not_verified` (Cabinet can't tell). Silence is never a safety result:
    anything unclear is `not_verified`."""
    # Compared as given (the caller resolves real paths): mountinfo speaks
    # in container paths, whatever the host running the tests is.
    key, backups = PurePosixPath(Path(key).as_posix()), PurePosixPath(Path(backups).as_posix())
    if key.is_relative_to(backups) or backups.is_relative_to(key.parent):
        return "shared"
    if mountinfo is None:
        return "not_verified"
    mounts = parse_mountinfo(mountinfo)
    key_mount, backup_mount = _mount_of(key, mounts), _mount_of(backups, mounts)
    if key_mount is None or backup_mount is None:
        return "not_verified"
    if key_mount.mount_id == backup_mount.mount_id:
        return "shared"
    if key_mount.device == backup_mount.device:
        a, b = _inside(key.parent, key_mount), _inside(backups, backup_mount)
        if a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
            return "shared"
        # Two folders on one filesystem: whether the backups' side is exported
        # with the key's (a shared parent) is the operator's to know.
        return "not_verified"
    if key_mount.fstype in LOCAL_FS and backup_mount.fstype in LOCAL_FS:
        return "separate"
    # A network or FUSE filesystem, or one Cabinet doesn't know: a server can
    # export one folder several ways, so only the operator can tell.
    return "not_verified"


def _read_mountinfo() -> str | None:
    try:
        return MOUNTINFO.read_text(encoding="utf-8")
    except OSError:
        return None


def location() -> str:
    """For the backup key: `secret` (a supplied file) or `environment` (a
    supplied variable), nothing to check either way; otherwise how the
    generated key sits relative to BACKUP_DIR."""
    where = source()
    if where == "file":
        return "secret"
    if where == "environment":
        return "environment"
    return compare_locations(
        key_path().resolve(), Path(get_settings().backup_dir).resolve(), _read_mountinfo()
    )


def secret_key_location() -> str | None:
    """The same check for SECRET_KEY_FILE, when that key is the generated one."""
    config = get_settings()
    if config.secret_key:
        return None
    return compare_locations(
        Path(config.secret_key_file).resolve(), Path(config.backup_dir).resolve(), _read_mountinfo()
    )


LOCATION_MESSAGES = {
    "shared": "Your backup key is stored beside your backups; supply it instead "
    "(BACKUP_KEY_FILE, or BACKUP_KEY).",
    "not_verified": "Cabinet cannot tell where your backup key is stored relative to your "
    "backups; supplying it (BACKUP_KEY_FILE, or BACKUP_KEY) removes the doubt.",
}
