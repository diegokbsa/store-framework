from ptcgp_bot.adb.discovery import KNOWN_EMULATOR_PORTS, discover_candidates, discover_devices


class FakeClient:
    def __init__(self, reachable, online):
        self.reachable = set(reachable)
        self.online = list(online)
        self.disconnected = []

    def start_server(self):
        pass

    def connect(self, address, timeout=3.0):
        return address in self.reachable

    def online_serials(self):
        return self.online

    def disconnect(self, address=None):
        self.disconnected.append(address)


def test_candidates_cover_known_emulators_and_are_unique():
    cands = discover_candidates(extra_ports=[5585], remote_hosts=["192.168.0.9", "10.0.0.2:5556"])
    addrs = [c.address for c in cands]
    assert len(addrs) == len(set(addrs))
    assert "127.0.0.1:7555" in addrs      # MuMu legacy
    assert "127.0.0.1:16384" in addrs     # MuMu 12
    assert "127.0.0.1:5555" in addrs      # LDPlayer / BlueStacks
    assert "127.0.0.1:62001" in addrs     # Nox
    assert "127.0.0.1:5585" in addrs      # extra
    assert "192.168.0.9:5555" in addrs    # remote sem porta
    assert "10.0.0.2:5556" in addrs


def test_ldplayer_step_two():
    spec = KNOWN_EMULATOR_PORTS["LDPlayer"]
    ports = [spec["base"] + i * spec["step"] for i in range(3)]
    assert ports == [5555, 5557, 5559]


def test_discover_devices_filters_offline_and_disconnects_them():
    client = FakeClient(reachable={"127.0.0.1:7555", "127.0.0.1:5555"},
                        online=["127.0.0.1:7555", "emulator-5554", "USB123"])
    serials = discover_devices(client, workers=4)
    assert serials == ["127.0.0.1:7555", "USB123", "emulator-5554"]
    assert "127.0.0.1:5555" in client.disconnected
