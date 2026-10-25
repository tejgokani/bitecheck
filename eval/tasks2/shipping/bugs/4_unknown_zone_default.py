import math

BASE = {"domestic": 5.00, "eu": 12.00, "intl": 25.00}


def shipping_cost(weight_kg: float, zone: str, express: bool = False) -> float:
    if zone not in BASE:
        zone = "intl"
    if weight_kg <= 0:
        raise ValueError(weight_kg)
    if zone == "domestic" and not express and weight_kg <= 0.5:
        return 0.0
    extra = max(0, math.ceil(weight_kg - 1))
    total = BASE[zone] + 2.00 * extra
    if express:
        total *= 2
    return round(total, 2)
