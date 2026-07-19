"""Shared test fixtures/helpers."""

from discbag.inventory import OwnedDisc

# Personal flight numbers used by the manufacturer-incomplete prototype helper below.
PROTOTYPE_PERSONAL_FLIGHT = {"speed": 10, "glide": 5, "turn": -1, "fade": 2}


def prototype_disc(name="Comanche", brand="Gateway", personal_flight=None, **user_kwargs):
    """A manufacturer-incomplete OwnedDisc with a complete personal_flight recorded —
    e.g. a hand-thrown prototype with no published manufacturer numbers. flight_known is
    True (via personal_flight) but raw d.speed/glide/turn/fade are all None, so this disc
    only participates safely when subsystems reason on roles.effective_flight rather than
    the raw manufacturer attributes.
    """
    d = OwnedDisc.from_db_record(
        {"name": name, "brand": brand, "category": "",
         "speed": None, "glide": None, "turn": None, "fade": None, "stability": ""},
        **user_kwargs)
    d.user.personal_flight = dict(personal_flight or PROTOTYPE_PERSONAL_FLIGHT)
    return d
