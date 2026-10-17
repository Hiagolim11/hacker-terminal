"""Saved SSH passwords and key setup, end to end, isolated from the real system.

Run under dbus-run-session: a throwaway gnome-keyring (own HOME and
XDG_RUNTIME_DIR, so the user's keyring is never touched), a real ssh
talking to a temporary sshd on 127.0.0.1, and ht-copy-key with fake
ssh-keygen/ssh-copy-id so no real key or authorized_keys file changes.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ASKPASS = PROJECT / "bin" / "ht-askpass"
COPY_KEY = PROJECT / "bin" / "ht-copy-key"
PASSWORD = "s3nh@ com espaço; $(id)"


def isolated_home() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ht-ssh-"))
    runtime = root / "run"
    runtime.mkdir(mode=0o700)
    os.environ.update({
        "HOME": str(root), "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(runtime),
    })
    return root


def start_keyring() -> None:
    result = subprocess.run(
        ["gnome-keyring-daemon", "--unlock", "--components=secrets", "--daemonize"],
        input="teste", capture_output=True, text=True, timeout=20, check=True,
    )
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key:
            os.environ[key] = value


def askpass(prompt: str, identifier: str = "umbrel") -> subprocess.CompletedProcess:
    # A new session has no controlling terminal: a question that must go to
    # the user fails instead of being answered.
    return subprocess.run(
        [str(ASKPASS), prompt], capture_output=True, text=True, timeout=20, start_new_session=True,
        env={**os.environ, "HACKER_TERMINAL_SSH_ID": identifier},
    )


def check_keyring_and_helper() -> None:
    sys.path.insert(0, str(PROJECT))
    from hackerterminal import passwords

    assert passwords.available(), "libsecret missing"
    assert passwords.lookup("umbrel") is None
    assert passwords.store("umbrel", "Umbrel", PASSWORD), "store failed"
    assert passwords.has_password("umbrel") and passwords.lookup("umbrel") == PASSWORD
    assert not any(PASSWORD in path.read_bytes().decode("latin-1") for path in Path(os.environ["XDG_DATA_HOME"]).rglob("*") if path.is_file()), \
        "password stored in clear text"

    # Each call comes from this same process, as if one ssh asked twice.
    first = askpass("umbrel@10.0.0.3's password: ")
    assert (first.returncode, first.stdout) == (0, PASSWORD + "\n"), f"first prompt: {first}"
    second = askpass("umbrel@10.0.0.3's password: ")
    assert second.returncode != 0 and PASSWORD not in second.stdout, "a refused password was sent again"
    host_key = askpass("Are you sure you want to continue connecting (yes/no/[fingerprint])? ")
    assert host_key.returncode != 0 and PASSWORD not in host_key.stdout, "password used for a host key question"
    other = askpass("x's password: ", identifier="nao-existe")
    assert other.returncode != 0 and not other.stdout, "unknown connection answered"

    assert passwords.forget("umbrel") and passwords.lookup("umbrel") is None
    print("chaveiro e ht-askpass: ok")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def check_real_ssh(root: Path) -> None:
    from hackerterminal import passwords

    if not (shutil.which("ssh") and Path("/usr/sbin/sshd").exists()):
        print("SKIP ssh real: ssh ou sshd ausente")
        return
    passwords.store("umbrel", "Umbrel", PASSWORD)
    work = root / "sshd"
    work.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(work / "host")], check=True)
    port = free_port()
    (work / "config").write_text(
        f"Port {port}\nListenAddress 127.0.0.1\nHostKey {work / 'host'}\nPidFile {work / 'pid'}\n"
        "UsePAM no\nPasswordAuthentication yes\nKbdInteractiveAuthentication no\nPubkeyAuthentication no\n"
        f"StrictModes no\nAuthorizedKeysFile {work / 'none'}\nLogLevel VERBOSE\n",
        encoding="utf-8",
    )
    log = work / "sshd.log"
    server = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(work / "config")], stderr=log.open("w"))
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        user = os.environ.get("USER") or os.getlogin()
        argv = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no", "-o", f"UserKnownHostsFile={work / 'known'}",
                "-o", "PreferredAuthentications=password", "-o", "NumberOfPasswordPrompts=3",
                "-o", "ConnectTimeout=5", f"{user}@127.0.0.1", "true"]
        env = {**os.environ, "SSH_ASKPASS": str(ASKPASS), "SSH_ASKPASS_REQUIRE": "force", "HACKER_TERMINAL_SSH_ID": "umbrel"}
        screen = run_in_terminal(argv, env, answer="digitada-pelo-usuario")
    finally:
        server.terminate()
        server.wait(timeout=10)
    markers = [  # this test process asked the helper directly earlier; skip that one
        marker for marker in Path(os.environ["XDG_RUNTIME_DIR"]).glob("hacker-terminal-askpass-*/*")
        if not marker.name.startswith(f"{os.getpid()}-")
    ]
    attempts = log.read_text(errors="replace").count("Failed password")
    # This sshd (not root) cannot check passwords, so every attempt fails:
    # the saved one goes once, then the user is asked on the terminal.
    assert len(markers) == 1, f"saved password used by {len(markers)} ssh processes"
    assert screen.count("A senha salva foi recusada") == 2, screen
    assert "digitada-pelo-usuario" not in screen, "typed password was echoed"
    assert attempts == 3 and PASSWORD not in screen, (attempts, screen)
    print("ssh real com senha do chaveiro: ok")


def run_in_terminal(argv: list[str], env: dict[str, str], answer: str) -> str:
    """Run ``argv`` on a pseudo-terminal, typing ``answer`` at each password question."""
    import pty
    import select

    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(argv[0], argv, env)
    screen = ""
    answered = 0
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096).decode(errors="replace")
            except OSError:
                break
            if not chunk:
                break
            screen += chunk
            if screen.count("password:") > answered and screen.rstrip().endswith("password:"):
                answered += 1  # once per question
                os.write(fd, (answer + "\n").encode())
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    return screen


def check_copy_key(root: Path) -> None:
    fake = root / "fakebin"
    fake.mkdir()
    calls = root / "calls"
    (fake / "ssh-keygen").write_text(
        f'#!/bin/sh\nprintf "keygen %s\\n" "$*" >> {calls}\n'
        'while [ $# -gt 0 ]; do [ "$1" = -f ] && key=$2; shift; done\n: > "$key"; : > "$key.pub"\n'
    )
    (fake / "ssh-copy-id").write_text(f'#!/bin/sh\nprintf "copy %s\\n" "$*" >> {calls}\n')
    for tool in fake.iterdir():
        tool.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    key = root / ".ssh" / "id_ed25519"
    for _ in range(2):
        result = subprocess.run(
            [str(COPY_KEY), "Umbrel", str(key), "-p", "2222", "umbrel@10.0.0.3"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=20,
        )
        assert result.returncode == 0 and "✓ Chave instalada" in result.stdout, result
    lines = calls.read_text().splitlines()
    assert [line.split()[0] for line in lines] == ["keygen", "copy", "copy"], lines  # key made only once
    assert lines[1] == f"copy -i {key}.pub -p 2222 umbrel@10.0.0.3", lines
    assert (key.parent.stat().st_mode & 0o777) == 0o700
    (fake / "ssh-copy-id").write_text("#!/bin/sh\nexit 1\n")
    failed = subprocess.run([str(COPY_KEY), "Umbrel", str(key), "umbrel@10.0.0.3"],
                            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=20)
    assert failed.returncode == 1 and "✗" in failed.stdout, failed
    print("ht-copy-key: ok")


def main() -> int:
    if not shutil.which("gnome-keyring-daemon"):
        print("SKIP: gnome-keyring-daemon ausente")
        return 0
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if os.environ.get("HT_PRIVATE_BUS") != "1" or "/run/user/" in bus:
        # Never talk to the user's real session keyring.
        print("execute: dbus-run-session -- env HT_PRIVATE_BUS=1 python3 tests/ssh_access.py", file=sys.stderr)
        return 2
    root = isolated_home()
    start_keyring()
    check_keyring_and_helper()
    check_real_ssh(root)
    check_copy_key(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
