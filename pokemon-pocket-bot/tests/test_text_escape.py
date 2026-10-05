from ptcgp_bot.adb.client import AdbClient, AdbDevice


class RecordingClient(AdbClient):
    def __init__(self):
        super().__init__(binary="adb")
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append(args)
        return ""


def test_text_escapes_spaces_and_specials():
    c = RecordingClient()
    d = AdbDevice(client=c, serial="x")
    d.text("Ash Ketchum&Co")
    cmd = c.calls[-1][-1]
    assert "input text" in cmd
    assert "%s" in cmd and "\\&" in cmd


def test_tap_and_swipe_commands():
    c = RecordingClient()
    d = AdbDevice(client=c, serial="x")
    d.tap(10.6, 20.2)
    assert c.calls[-1] == ("-s", "x", "shell", "input tap 10 20")
    d.swipe(1, 2, 3, 4, 150)
    assert c.calls[-1][-1] == "input swipe 1 2 3 4 150"
