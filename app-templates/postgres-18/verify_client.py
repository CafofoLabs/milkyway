"""Prove the client reaches PostgreSQL through the sidecar and requires SCRAM."""

import json
import os
import socket
import struct


def verify(address, port, user):
    payload = b"user\0" + user.encode() + b"\0database\0postgres\0\0"
    with socket.create_connection((address, port), timeout=5) as connection:
        connection.sendall(struct.pack("!II", len(payload) + 8, 196608) + payload)
        stream = connection.makefile("rb")
        header = stream.read(5)
        if len(header) != 5 or header[:1] != b"R":
            raise ValueError("Expected a PostgreSQL authentication challenge")
        length = struct.unpack("!I", header[1:])[0]
        if not 8 <= length <= 4096:
            raise ValueError("Invalid PostgreSQL authentication frame")
        response = stream.read(length - 4)
        if (
            len(response) != length - 4
            or struct.unpack("!I", response[:4])[0] != 10
            or b"SCRAM-SHA-256\0" not in response
        ):
            raise ValueError("Expected SCRAM-SHA-256 password authentication")


if __name__ == "__main__":
    parameters = json.loads(os.environ["MAPPED_APP_PARAMETERS"])
    verify(
        os.environ["MAPPED_APP_TAILSCALE_IP"],
        int(os.environ["MAPPED_APP_PORT"]),
        parameters["user"],
    )
    print("Client reached PostgreSQL through Tailscale; SCRAM-SHA-256 required")
