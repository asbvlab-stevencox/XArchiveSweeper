import zipfile
from pathlib import Path

import pytest

from xsweeper.api import Result
from xsweeper.archive import load_posts
from xsweeper.cli import main
from xsweeper.filters import Filter, load_id_csv, parse_date, parse_types
from xsweeper.runner import Runner
from xsweeper.state import State
from xsweeper.tiers import TIERS

FX = Path(__file__).parent / "fixtures" / "tweets.js"


def test_parse_and_classify():
    ps = {p.id: p for p in load_posts(FX)}
    assert [ps[i].type for i in "12345"] == ["original", "reply", "reply", "retweet", "original"]
    assert ps["3"].likes == 25


def test_zip(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FX, "data/tweets.js")
    assert len(load_posts(z)) == 5


def test_filters(tmp_path):
    ps = load_posts(FX)
    ids = lambda f: [p.id for p in f.apply(ps)]
    assert ids(Filter(max_likes=1, types=parse_types("reply,original"))) == ["1", "2", "5"]
    assert ids(Filter(max_likes=1, exclude=["secret"])) == ["1", "2", "4"]
    assert ids(Filter(include=["reply"])) == ["2", "3"]
    assert ids(Filter(since=parse_date("2024-01-01"))) == ["4", "5"]
    assert ids(Filter(max_retweets=0, types={"original"})) == ["1", "5"]
    c = tmp_path / "ids.csv"
    c.write_text("id,x\n2,a\n5,b\n")
    assert ids(Filter(ids=load_id_csv(c))) == ["2", "5"]
    with pytest.raises(ValueError):
        parse_types("reply,bogus")


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def delete_post(self, pid):
        self.calls.append(("del", pid))
        return self.script.pop(0)

    def unretweet(self, uid, sid):
        self.calls.append(("unrt", sid))
        return self.script.pop(0)


def ok(rem=10, reset=None):
    return Result(200, True, rem, reset)


def test_runner_respects_429_and_resumes(tmp_path):
    ps = load_posts(FX)[:3]
    sleeps = []
    c = FakeClient([ok(), Result(429, False, 0, 1000), ok(), Result(404, False, 5, None)])
    st = State(tmp_path / "s.sqlite")
    r = Runner(c, st, TIERS["pro"], sleep=sleeps.append, clock=lambda: 900, log=lambda m: None)
    stats = r.run(ps)
    assert stats == {"deleted": 2, "failed": 0, "skipped": 1}
    assert 102 in sleeps  # waited until reset (+2s)
    # second run: nothing left to do
    c2 = FakeClient([])
    assert Runner(c2, st, TIERS["pro"], sleep=lambda s: None, log=lambda m: None).run(ps)["deleted"] == 0
    assert c2.calls == []


def test_free_daily_cap(tmp_path):
    ps = load_posts(FX)
    tier = TIERS["free"].__class__(**{**TIERS["free"].__dict__, "daily_cap": 2})
    c = FakeClient([ok(), ok(), ok()])
    st = State(tmp_path / "s.sqlite")
    stats = Runner(c, st, tier, sleep=lambda s: None, log=lambda m: None).run(ps)
    assert stats["deleted"] == 2 and len(c.calls) == 2


def test_header_remaining_zero_waits(tmp_path):
    sleeps = []
    c = FakeClient([ok(rem=0, reset=2000), ok()])
    Runner(c, State(tmp_path / "s"), TIERS["payg"], sleep=sleeps.append, clock=lambda: 1000,
           log=lambda m: None).run(load_posts(FX)[:2])
    assert sleeps[0] == 1002


def test_auth_error_stops(tmp_path):
    c = FakeClient([Result(401, False, None, None, "Unauthorized")])
    st = State(tmp_path / "s")
    s = Runner(c, st, TIERS["pro"], sleep=lambda s: None, log=lambda m: None).run(load_posts(FX))
    assert s["failed"] == 1 and len(c.calls) == 1


def test_unretweet_endpoint_when_source_known(tmp_path, monkeypatch):
    import xsweeper.api as api

    class Resp:
        status_code = 200
        headers = {"x-rate-limit-remaining": "49", "x-rate-limit-reset": "123"}
        text = ""
        def __init__(self, data): self._d = data
        def json(self): return {"data": self._d}

    class Sess:
        def __init__(self): self.urls = []
        def request(self, m, url, **kw):
            self.urls.append((m, url))
            return Resp({"retweeted": False} if "retweets" in url else {"deleted": True})

    s = Sess()
    cl = api.XClient(session=s, bearer="t")
    assert cl.delete_post("5").ok and cl.unretweet("u1", "77").remaining == 49
    assert s.urls == [("DELETE", "https://api.x.com/2/tweets/5"),
                      ("DELETE", "https://api.x.com/2/users/u1/retweets/77")]


def test_cli_dry_run_default(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["run", str(FX), "--max-likes", "1", "--types", "reply,original"]) == 0
    out = capsys.readouterr().out
    assert "Matched: 3" in out and "DRY RUN" in out


REAL = Path("/workspace/xarchive")


@pytest.mark.skipif(not REAL.exists(), reason="real archive not present")
def test_real_archive_parser():
    src = REAL / "extract" / "data" / "tweets.js"
    ps = load_posts(src if src.exists() else next(REAL.glob("*.zip")))
    assert len(ps) > 1000
    assert all(p.type in {"reply", "original", "retweet"} for p in ps)
    sel = Filter(max_likes=1, types={"reply", "original"}).apply(ps)
    assert 0 < len(sel) < len(ps)
