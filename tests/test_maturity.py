from datetime import date

from discbag import maturity
from discbag.inventory import OwnedDisc


def owned(mold, *, brand="Innova", speed=5, category="Midrange",
          turn=0, fade=1, uses=0, last=None, fav=False, added="2026-01-01"):
    rec = {"name": mold, "brand": brand, "category": category,
           "speed": speed, "glide": 5, "turn": turn, "fade": fade, "stability": ""}
    return OwnedDisc.from_db_record(rec, use_count=uses, last_used=last,
                                    favorite=fav, date_added=added)


TODAY = date(2026, 7, 14)


# ---------- individual signals ----------

def test_sufficient_usage_true_when_enough_and_recent():
    bag = [owned("Buzzz", uses=8, last="2026-07-10"),
           owned("Roc", uses=5, last="2026-07-01")]
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is True


def test_sufficient_usage_false_when_too_few_uses():
    bag = [owned("Buzzz", uses=3, last="2026-07-10")]
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is False
    assert "recorded use" in s.text.lower()


def test_sufficient_usage_false_when_stale():
    bag = [owned("Buzzz", uses=20, last="2026-01-01")]   # >90 days before TODAY
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is False


def test_settled_core_true_when_concentrated():
    # 90 uses on 2 discs, 5 more discs barely used -> a small core carries most throws.
    bag = [owned("Buzzz", uses=50), owned("Roc", uses=40)]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    s = maturity.settled_core(bag)
    assert s.met is True
    assert "discs" in s.text


def test_settled_core_false_when_spread_out():
    bag = [owned(f"D{i}", uses=5) for i in range(9)]      # even spread, no core
    s = maturity.settled_core(bag)
    assert s.met is False


def test_settled_core_false_with_no_usage():
    assert maturity.settled_core([owned("Buzzz", uses=0)]).met is False


def test_new_molds_counts_only_new_molds_recently():
    # Two copies of Wave (one old, one recent) = refinement, not a new mold.
    all_discs = [
        owned("Wave", brand="MVP", added="2024-01-01"),
        owned("Wave", brand="MVP", added="2026-07-01"),   # backup, recent
        owned("Roc", added="2020-01-01"),
    ]
    s = maturity.not_chasing_new_molds(all_discs, TODAY)
    assert s.met is True                                  # no NEW mold recently


def test_new_molds_flags_genuinely_new_recent_molds():
    all_discs = [owned("Roc", added="2020-01-01"),
                 owned("Zone", added="2026-07-01"),        # new mold, recent
                 owned("Buzzz", added="2026-07-02")]       # new mold, recent
    s = maturity.not_chasing_new_molds(all_discs, TODAY)
    assert s.met is False                                  # 2 new > MAX_RECENT_NEW_MOLDS (1)
    assert "experimenting" in s.text.lower()


def test_established_favorites_threshold():
    bag = [owned("A", fav=True), owned("B", fav=True), owned("C", fav=True)]
    assert maturity.established_favorites(bag).met is True
    assert maturity.established_favorites([owned("A", fav=True)]).met is False


# ---------- assess_phase (gate + resolution), roles.assess monkeypatched ----------

class _FakeRole:
    def __init__(self, name, optional=False):
        self.name = name
        self.optional = optional


class _FakeCoverage:
    def __init__(self, covered, priority, optional=False, name="Role"):
        self.covered = covered
        self.priority = priority
        self.role = _FakeRole(name, optional)


def test_phase_discovery_when_meaningful_gap(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess",
                        lambda bag, profile=None: [_FakeCoverage(False, "High", name="Overstable mid")])
    phase, signals = maturity.assess_phase([owned("Buzzz", uses=20, last="2026-07-10")],
                                           [], None, TODAY)
    assert phase == "Discovery"
    assert any("overstable mid" in s.text.lower() for s in signals)


def test_phase_ignores_low_priority_and_optional_gaps(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [
        _FakeCoverage(True, "Satisfied"),
        _FakeCoverage(False, "Low", name="Utility driver"),      # low → not meaningful
        _FakeCoverage(False, "High", optional=True, name="2nd distance driver"),  # optional
    ])
    bag = [owned("Buzzz", uses=30, last="2026-07-10"), owned("Roc", uses=1)]
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"


def test_phase_developed_when_covered_settled_and_used(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    bag = [owned("Buzzz", uses=50, last="2026-07-10"), owned("Roc", uses=40, last="2026-07-08")]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"


def test_phase_developing_when_usage_insufficient(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    bag = [owned("Buzzz", uses=2, last="2026-07-10")]      # < MIN_USES
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developing"


def test_developed_stays_developed_after_new_molds(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    # Settled core with real usage...
    bag = [owned("Buzzz", uses=50, last="2026-07-10"), owned("Roc", uses=40, last="2026-07-08")]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    # ...plus two brand-new molds bought recently but barely thrown (curiosity).
    bag += [owned("Zone", added="2026-07-01", uses=0), owned("Mako3", added="2026-07-02", uses=0)]
    phase, signals = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"                                    # not demoted
    assert any(("experimenting" in s.text.lower()) and not s.met for s in signals)  # supporting •
