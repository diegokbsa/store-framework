import threading

import pytest

from ptcgp_bot.accounts.email_store import EmailStatus, EmailStore, plus_alias


@pytest.fixture
def store(tmp_path):
    s = EmailStore(tmp_path / "t.db")
    yield s
    s.close()


def test_add_and_validate(store):
    assert store.add("A@Example.com")
    assert not store.add("a@example.com")       # duplicado (case-insensitive)
    assert not store.add("nao-e-email")
    assert store.counts()["available"] == 1


def test_add_many_with_passwords_and_comments(store):
    added, skipped = store.add_many([
        "# comentario", "", "x@y.com:senha1", "z@y.com,senha2", "invalido", "x@y.com",
    ])
    assert (added, skipped) == (2, 2)
    assert store.get("x@y.com").password == "senha1"
    assert store.get("z@y.com").password == "senha2"


def test_plus_alias_and_generate(store):
    assert plus_alias("eu+old@gmail.com", 7) == "eu+0007@gmail.com"
    assert store.generate_aliases("eu@gmail.com", 3) == 3
    assert [e.email for e in store.list()] == [
        "eu+0001@gmail.com", "eu+0002@gmail.com", "eu+0003@gmail.com",
    ]
    with pytest.raises(ValueError):
        store.generate_aliases("ruim", 2)


def test_acquire_is_atomic_across_threads(store):
    store.add_many([f"u{i}@x.com" for i in range(20)])
    got = []
    lock = threading.Lock()

    def worker(dev):
        for _ in range(5):
            e = store.acquire(dev)
            if e:
                with lock:
                    got.append(e.email)

    threads = [threading.Thread(target=worker, args=(f"dev{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 20
    assert len(set(got)) == 20
    assert store.counts()["assigned"] == 20
    assert store.acquire("devX") is None


def test_status_transitions_and_release(store):
    store.add("a@b.com")
    e = store.acquire("dev1")
    assert e.status == EmailStatus.ASSIGNED and e.device == "dev1"
    store.set_status("a@b.com", EmailStatus.USED, account_ref="/tmp/acc.xml")
    assert store.get("a@b.com").account_ref == "/tmp/acc.xml"
    store.set_status("a@b.com", EmailStatus.VERIFIED)
    assert store.list(EmailStatus.VERIFIED)[0].email == "a@b.com"
    store.add("c@b.com")
    store.acquire("dev2")
    assert store.reset_assigned() == 1
    assert store.get("c@b.com").status == EmailStatus.AVAILABLE


def test_verification_log(store):
    store.add("a@b.com")
    store.log_verification("a@b.com", "123456", True, "ok")
    hist = store.verification_history()
    assert hist[0]["code"] == "123456" and hist[0]["ok"] == 1
