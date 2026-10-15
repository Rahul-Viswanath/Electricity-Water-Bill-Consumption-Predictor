import pytest

from predictor.tariff import Slab, Tariff, compute_bill, energy_charge, load_tariffs


def make_tariff(mode="telescopic", fixed=0.0, tax=0.0, slabs=((100, 3.0), (200, 5.0), (None, 8.0))):
    return Tariff(
        name="test",
        unit_label="kWh",
        mode=mode,
        slabs=tuple(Slab(upto, rate) for upto, rate in slabs),
        fixed_charge=fixed,
        tax_percent=tax,
    )


def test_telescopic_within_first_slab():
    assert energy_charge(60, make_tariff()) == pytest.approx(180)


def test_telescopic_exactly_on_boundary():
    assert energy_charge(100, make_tariff()) == pytest.approx(300)


def test_telescopic_across_two_slabs():
    # 100 * 3 + 50 * 5
    assert energy_charge(150, make_tariff()) == pytest.approx(550)


def test_telescopic_into_open_ended_slab():
    # 100 * 3 + 100 * 5 + 50 * 8
    assert energy_charge(250, make_tariff()) == pytest.approx(1200)


def test_flat_slab_uses_rate_of_slab_the_total_lands_in():
    tariff = make_tariff(mode="flat_slab")
    assert energy_charge(150, tariff) == pytest.approx(150 * 5)
    assert energy_charge(250, tariff) == pytest.approx(250 * 8)


def test_bill_adds_fixed_charge_then_tax():
    bill = compute_bill(150, make_tariff(fixed=100, tax=10))
    assert bill.energy_charge == pytest.approx(550)
    assert bill.tax == pytest.approx(65)  # 10% of (550 + 100)
    assert bill.total == pytest.approx(715)


def test_zero_units_still_pays_fixed_charge():
    bill = compute_bill(0, make_tariff(fixed=100, tax=10))
    assert bill.energy_charge == 0
    assert bill.total == pytest.approx(110)


@pytest.mark.parametrize(
    "slabs",
    [
        ((100, 3.0), (200, 5.0)),  # last slab is capped
        ((200, 3.0), (100, 5.0), (None, 8.0)),  # not increasing
        ((None, 3.0), (None, 5.0)),  # open-ended slab in the middle
        ((100, -1.0), (None, 5.0)),  # negative rate
    ],
)
def test_invalid_slabs_are_rejected(slabs):
    with pytest.raises(ValueError):
        make_tariff(slabs=slabs)


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        make_tariff(mode="surprise")


def test_default_tariff_file_loads():
    tariffs = load_tariffs()
    assert {"electricity", "water"} <= tariffs.keys()
