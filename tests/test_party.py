"""Plan 028 Phase 3 — the party model.

NEW-BEHAVIOR and FAILURE-MODE. All of these fail until backend/party.py exists.

The model carries AGES and derives COUNTS, because the two source families
disagree about what a party is: Kayak's URL takes ages, while both Google-side
libraries take counts by bucket (verified against the installed packages --
fli's PassengerInfo and fast_flights' Passengers both expose exactly
adults/children/infants_in_seat/infants_on_lap and no age at all).

infants_on_lap is the one field no age can imply: a 1-year-old may fly on a lap
or in a purchased seat, and that is a booking choice. It is therefore explicit,
which is why the roadmap's original `child_ages = [6]` shape was insufficient.
"""


def test_a_party_defaults_to_one_adult():
    from backend.party import Party
    assert Party().adults == 1


def test_default_party_has_no_children():
    from backend.party import Party
    assert Party().child_ages == ()


def test_total_travellers_counts_adults_children_and_infants():
    from backend.party import Party
    party = Party(adults=2, child_ages=(6, 9), infants_on_lap=1)
    # 2 adults + 2 children + 1 lap infant; the infant has no age entry of its
    # own, so it is counted from infants_on_lap.
    assert party.total_travellers == 5


# --- bucket boundaries: Google buckets ages, so the edges are load-bearing ---

def test_age_eleven_counts_as_a_child():
    from backend.party import Party
    assert Party(child_ages=(11,)).children == 1


def test_age_twelve_counts_as_an_adult_not_a_child():
    from backend.party import Party
    assert Party(adults=1, child_ages=(12,)).children == 0


def test_age_twelve_is_added_to_the_adult_count():
    from backend.party import Party
    assert Party(adults=1, child_ages=(12,)).adults_total == 2


def test_age_two_counts_as_a_child_not_an_infant():
    from backend.party import Party
    assert Party(child_ages=(2,)).children == 1


def test_age_one_counts_as_an_infant_not_a_child():
    from backend.party import Party
    assert Party(child_ages=(1,)).children == 0


def test_age_zero_counts_as_an_infant():
    from backend.party import Party
    assert Party(adults=1, child_ages=(0,)).infants_in_seat == 1


# --- lap vs seat: the distinction no age can express ---

def test_an_infant_on_a_lap_is_not_also_counted_in_a_seat():
    from backend.party import Party
    assert Party(adults=1, child_ages=(1,), infants_on_lap=1).infants_in_seat == 0


def test_a_second_infant_without_a_lap_takes_a_seat():
    from backend.party import Party
    party = Party(adults=2, child_ages=(1, 1), infants_on_lap=1)
    assert party.infants_in_seat == 1


# --- validation ---

def test_a_party_with_no_travellers_is_rejected():
    import pytest
    from backend.party import Party
    with pytest.raises(ValueError):
        Party(adults=0).validate()


def test_a_negative_adult_count_is_rejected():
    import pytest
    from backend.party import Party
    with pytest.raises(ValueError):
        Party(adults=-1).validate()


def test_a_negative_child_age_is_rejected():
    import pytest
    from backend.party import Party
    with pytest.raises(ValueError):
        Party(adults=1, child_ages=(-1,)).validate()


def test_more_lap_infants_than_adults_is_rejected():
    """A lap infant needs a lap to sit on."""
    import pytest
    from backend.party import Party
    with pytest.raises(ValueError):
        Party(adults=1, child_ages=(1, 1), infants_on_lap=2).validate()


def test_more_lap_infants_than_under_twos_is_rejected():
    import pytest
    from backend.party import Party
    with pytest.raises(ValueError):
        Party(adults=2, child_ages=(6,), infants_on_lap=1).validate()


def test_a_valid_party_passes_validation():
    from backend.party import Party
    assert Party(adults=2, child_ages=(6, 1), infants_on_lap=1).validate() is None


# --- scale ---

def test_a_large_party_is_accepted():
    from backend.party import Party
    party = Party(adults=9, child_ages=tuple([8] * 8))
    assert party.total_travellers == 17


def test_a_party_is_frozen_so_it_cannot_be_mutated_after_creation():
    """The freeze rule is enforced at the tracker level, but an immutable Party
    means no code path can quietly re-point one mid-search."""
    import dataclasses
    import pytest
    from backend.party import Party
    with pytest.raises(dataclasses.FrozenInstanceError):
        Party().adults = 3
