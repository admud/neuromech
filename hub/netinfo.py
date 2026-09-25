"""Find LAN addresses without trusting a single adapter on Windows."""

import socket


def lan_ipv4_addresses():
    found = []
    # UDP connect chooses the address on the default route without sending data.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            found.append(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:
        import psutil
        for entries in psutil.net_if_addrs().values():
            for entry in entries:
                if entry.family == socket.AF_INET:
                    found.append(entry.address)
    except ImportError:
        pass
    return list(dict.fromkeys(ip for ip in found if not ip.startswith(("127.", "169.254."))))
