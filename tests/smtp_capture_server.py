"""Minimaler SMTP-Server (stdlib), der genau eine Nachricht abfängt.

Dient als lokaler Empfänger für End-to-End-Versandtests – ohne externe
Abhängigkeiten und ohne echte Zustellung.
"""
from __future__ import annotations

import socket
import threading


class SMTPCaptureServer:
    """Spricht so viel SMTP, wie zum Empfang einer Mail nötig ist."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.mail_from: str = ""
        self.rcpt_to: list[str] = []
        self.data: str = ""
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "SMTPCaptureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def wait(self, timeout: float = 10.0) -> None:
        self._thread.join(timeout)

    def _serve(self) -> None:
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            f = conn.makefile("rwb")
            conn.sendall(b"220 capture ESMTP\r\n")
            in_data = False
            data_lines: list[str] = []
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace")
                if in_data:
                    if line.rstrip("\r\n") == ".":
                        self.data = "".join(data_lines)
                        in_data = False
                        conn.sendall(b"250 OK: queued\r\n")
                        continue
                    # RFC 5321 Transparenz: führenden Punkt entstuffen
                    data_lines.append(line[1:] if line.startswith("..") else line)
                    continue

                cmd = line.strip()
                upper = cmd.upper()
                if upper.startswith(("EHLO", "HELO")):
                    conn.sendall(b"250-capture\r\n250 OK\r\n")
                elif upper.startswith("MAIL FROM"):
                    self.mail_from = cmd[cmd.find(":") + 1:].strip()
                    conn.sendall(b"250 OK\r\n")
                elif upper.startswith("RCPT TO"):
                    self.rcpt_to.append(cmd[cmd.find(":") + 1:].strip())
                    conn.sendall(b"250 OK\r\n")
                elif upper == "DATA":
                    in_data = True
                    conn.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                elif upper == "QUIT":
                    conn.sendall(b"221 Bye\r\n")
                    break
                elif upper.startswith("RSET"):
                    conn.sendall(b"250 OK\r\n")
                else:
                    conn.sendall(b"250 OK\r\n")
