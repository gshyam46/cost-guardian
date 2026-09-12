"""Owned loopback TCP relay used to cut database transport deterministically."""
import select
import socket
import socketserver
import threading


class MongoProxy:
    def __init__(self, host, port):
        assert host in ("127.0.0.1", "localhost", "::1") and 1 <= port <= 65535
        self.enabled = True
        self.connections = set()
        self.lock = threading.Lock()
        proxy = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                upstream = None
                try:
                    if not proxy.enabled: return
                    upstream = socket.create_connection((host, port), timeout=2)
                    with proxy.lock: proxy.connections.update((self.request, upstream))
                    while proxy.enabled:
                        ready, _, _ = select.select((self.request, upstream), (), (), .1)
                        for connection in ready:
                            data = connection.recv(65536)
                            if not data: return
                            target = upstream if connection is self.request else self.request
                            target.sendall(data)
                except (OSError, ValueError): pass
                finally:
                    with proxy.lock:
                        proxy.connections.discard(self.request)
                        if upstream: proxy.connections.discard(upstream)
                    if upstream: upstream.close()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)

    def cut(self):
        self.enabled = False
        with self.lock:
            for connection in list(self.connections):
                try: connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                connection.close()

    def restore(self): self.enabled = True
    def __enter__(self):
        self.thread.start()
        return self
    def __exit__(self, *_args):
        self.cut()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()
