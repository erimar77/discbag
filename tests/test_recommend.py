from discbag import recommend
from discbag.inventory import Disc, OwnedDisc
from discbag.player import PlayerProfile

MAKO3 = Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)
WIZARD = Disc(name="Wizard", speed=2, glide=3, turn=0, fade=2)
LEOPARD = Disc(name="Leopard", speed=6, glide=5, turn=-2, fade=1)
FIREBIRD = Disc(name="Firebird", speed=9, glide=3, turn=0, fade=4)
DESTROYER = Disc(name="Destroyer", speed=12, glide=5, turn=-1, fade=3)


def filled_roles(result):
    return {f.role.name: f.disc for f in result.filled}


def test_build_bag_fills_role_with_qualifying_disc():
    result = recommend.build_bag([MAKO3])
    assert filled_roles(result).get("Straight mid") is MAKO3


def test_build_bag_reports_unfilled_roles_as_gaps():
    result = recommend.build_bag([WIZARD])  # only a putter
    gap_names = {r.name for r in result.gaps}
    assert "Utility driver" in gap_names
    assert "Straight mid" in gap_names


def test_build_bag_uses_distinct_discs_when_available():
    # A bag with a distinct qualifier for every role -> no disc is reused.
    bag = [
        WIZARD,                                             # Putting
        Disc(name="Pathfinder", speed=4, glide=5, turn=0, fade=1),   # Straight approach
        Disc(name="Zone", speed=4, glide=3, turn=0, fade=3),         # Overstable approach
        MAKO3,                                              # Straight mid
        Disc(name="Justice", speed=5, glide=4, turn=0, fade=3),      # Overstable mid
        LEOPARD,                                            # Understable fairway
        Disc(name="Teebird", speed=7, glide=5, turn=0, fade=2),      # Control fairway
        FIREBIRD,                                           # Utility driver
        DESTROYER,                                          # Distance driver
    ]
    result = recommend.build_bag(bag)
    discs = [f.disc for f in result.filled]
    assert len(discs) == len(set(id(d) for d in discs))
    assert not result.gaps


def test_build_bag_size_limits_fills():
    result = recommend.build_bag([MAKO3, WIZARD, LEOPARD, FIREBIRD, DESTROYER], size=2)
    assert len(result.filled) == 2


def test_build_bag_size_separates_omitted_from_gaps():
    bag = [MAKO3, WIZARD, LEOPARD, FIREBIRD, DESTROYER]
    genuine = {r.name for r in recommend.build_bag(bag).gaps}   # no-size genuine gaps
    result = recommend.build_bag(bag, size=1)
    assert len(result.filled) == 1
    omitted = {r.name for r in result.omitted}
    assert omitted                                              # some roles were trimmed
    assert omitted.isdisjoint(genuine)                         # trimmed != genuine gaps
    assert {r.name for r in result.gaps} == genuine            # gaps unchanged by size


def test_build_bag_no_size_has_empty_omitted():
    result = recommend.build_bag([MAKO3, WIZARD])
    assert result.omitted == []


def test_build_bag_situation_narrows_roles():
    result = recommend.build_bag([WIZARD], situation="minimal")
    all_roles = {f.role.name for f in result.filled} | {r.name for r in result.gaps}
    # Minimal omits e.g. the understable fairway role.
    assert "Understable fairway" not in all_roles
    assert "Straight mid" in all_roles


# ---------- goals ----------

def _owned(name, **flight):
    return OwnedDisc.from_db_record(dict(name=name, brand="Test", **flight))


def _control_pick(result):
    return {f.role.name: f.disc.name for f in result.filled}.get("Control fairway")


def test_goal_coverage_picks_best_fit_but_development_picks_in_power():
    prof = PlayerProfile(max_distance=275)  # ~speed 6.6
    fast = Disc(name="EagleX", speed=8, glide=4, turn=0, fade=2.5)   # best fit, needs power
    slow = Disc(name="Teebird", speed=7, glide=5, turn=0, fade=2)    # within power
    bag = [fast, slow]
    assert _control_pick(recommend.build_bag(bag, goal="coverage")) == "EagleX"
    assert _control_pick(recommend.build_bag(bag, goal="development", profile=prof)) == "Teebird"


def test_goal_confidence_prefers_the_disc_you_use_most():
    a = _owned("Mako3", speed=5, glide=5, turn=0, fade=0)
    b = _owned("Buzzz", speed=5, glide=4, turn=-1, fade=1)
    b.user.use_count = 40
    picked = {f.role.name: f.disc.name for f in recommend.build_bag([a, b], goal="confidence").filled}
    assert picked.get("Straight mid") == "Buzzz"


def test_goal_confidence_prefers_recently_used_disc():
    a = _owned("Mako3", speed=5, glide=5, turn=0, fade=0)
    b = _owned("Buzzz", speed=5, glide=4, turn=-1, fade=1)
    a.user.last_used = "2026-01-01T00:00:00+00:00"   # long ago
    b.user.last_used = "2026-07-02T00:00:00+00:00"   # recent
    picked = {f.role.name: f.disc.name for f in
              recommend.build_bag([a, b], goal="confidence", today="2026-07-03").filled}
    assert picked.get("Straight mid") == "Buzzz"


def test_goal_development_prefers_a_lower_use_disc_for_practice():
    a = _owned("Mako3", speed=5, glide=5, turn=0, fade=0)
    b = _owned("Buzzz", speed=5, glide=4, turn=-1, fade=1)
    a.user.use_count = 30   # well-worn
    picked = {f.role.name: f.disc.name for f in
              recommend.build_bag([a, b], goal="development").filled}
    assert picked.get("Straight mid") == "Buzzz"


def test_goal_fun_prefers_a_not_recently_used_disc():
    a = _owned("Mako3", speed=5, glide=5, turn=0, fade=0)
    b = _owned("Buzzz", speed=5, glide=4, turn=-1, fade=1)
    a.user.last_used = "2026-07-02T00:00:00+00:00"   # recent -> less novel
    b.user.last_used = "2026-01-01T00:00:00+00:00"   # neglected -> fun to revisit
    picked = {f.role.name: f.disc.name for f in
              recommend.build_bag([a, b], goal="fun", today="2026-07-03").filled}
    assert picked.get("Straight mid") == "Buzzz"


def test_goal_fun_prefers_a_favorite():
    a = _owned("Mako3", speed=5, glide=5, turn=0, fade=0)
    b = _owned("Buzzz", speed=5, glide=4, turn=-1, fade=1)
    b.user.favorite = True
    picked = {f.role.name: f.disc.name for f in recommend.build_bag([a, b], goal="fun").filled}
    assert picked.get("Straight mid") == "Buzzz"


# ---------- rotation ----------

def test_comparable_group_excludes_far_worse():
    a, b, c = Disc(name="A"), Disc(name="B"), Disc(name="C")
    group = recommend.comparable_group([(1.0, a), (1.5, b), (3.0, c)], threshold=1.0)
    assert [d.name for d in group] == ["A", "B"]


def test_rotation_can_pick_a_comparable_alternative():
    class LastRNG:
        def choice(self, seq):
            return seq[-1]

    bag = [MAKO3, Disc(name="Buzzz", speed=5, glide=4, turn=-1, fade=1)]  # equal-fit straight mids
    result = recommend.build_bag(bag, rotate=True, rng=LastRNG())
    picked = {f.role.name: f.disc.name for f in result.filled}
    assert picked.get("Straight mid") == "Buzzz"


def test_no_rotation_is_deterministic_best():
    bag = [MAKO3, Disc(name="Buzzz", speed=5, glide=4, turn=-1, fade=1)]
    r1 = {f.role.name: f.disc.name for f in recommend.build_bag(bag).filled}
    r2 = {f.role.name: f.disc.name for f in recommend.build_bag(bag).filled}
    assert r1 == r2


# ---------- explainable scoring ----------

def _role(name):
    from discbag import roles
    return next(r for r in roles.ROLES if r.name == name)


def test_score_disc_components_sum_to_total():
    s = recommend.score_disc(MAKO3, _role("Straight mid"), goal="coverage")
    assert sum(c.points for c in s.components) == s.total
    assert any(c.label == "Role fit" for c in s.components)


def test_better_fit_scores_higher():
    mid = _role("Straight mid")
    good = recommend.score_disc(MAKO3, mid).total                      # 5/0/0, great fit
    worse = recommend.score_disc(Disc(name="Off", speed=6.5, glide=5, turn=0.5, fade=1.5),
                                 mid).total
    assert good > worse


def test_development_breakdown_names_its_parts():
    prof = PlayerProfile(max_distance=275)
    s = recommend.score_disc(FIREBIRD, _role("Utility driver"),
                             goal="development", profile=prof)
    labels = {c.label for c in s.components}
    assert "Power mismatch" in labels


def test_goal_penalty_still_equals_sum_of_components():
    # Refactor guard: the decomposed components must sum to the original penalty.
    prof = PlayerProfile(max_distance=275)
    for goal in ("development", "confidence", "tournament", "fun"):
        parts = sum(v for _, v in recommend._goal_components(goal, MAKO3, prof))
        assert abs(parts - recommend._goal_penalty(goal, MAKO3, prof)) < 1e-9


def test_build_bag_explained_reports_selection_and_rotation():
    class LastRNG:
        def choice(self, seq):
            return seq[-1]

    bag = [MAKO3, Disc(name="Buzzz", speed=5, glide=4, turn=-1, fade=1)]
    decisions = recommend.build_bag_explained(bag, rotate=True, rng=LastRNG())
    mid = next(d for d in decisions if d.role.name == "Straight mid")
    assert mid.selected is not None
    assert len(mid.comparable) == 2       # both are comparable straight mids
    assert mid.rotated is True            # rng picked the non-top candidate
    assert [c.disc.name for c in mid.candidates]  # ranked candidates present


# ---------- Unknown-flight discs ----------

def test_build_bag_ignores_unknown_flight():
    from discbag.inventory import Disc
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    result = recommend.build_bag([known, unknown])
    assert all(f.disc is not unknown for f in result.filled)


# ---------- manufacturer-incomplete + personal-complete prototypes ----------

def test_build_bag_development_goal_handles_prototype_without_crashing():
    from tests.conftest import prototype_disc
    d = prototype_disc()   # personal speed=10 glide=5 turn=-1 fade=2 -> qualifies Control fairway
    prof = PlayerProfile(max_distance=200)   # weaker arm than the prototype needs
    result = recommend.build_bag([d], goal="development", profile=prof)
    filled = {f.role.name: f.disc for f in result.filled}
    assert filled.get("Control fairway") is d
