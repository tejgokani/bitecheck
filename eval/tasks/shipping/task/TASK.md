# Task: shipping cost

Implement `shipping_cost(weight_kg: float, zone: str, express: bool = False) -> float` in `shipping.py`.

Rules:
1. Base price by zone: `"domestic"` 5.00, `"eu"` 12.00, `"intl"` 25.00. Any other zone raises `ValueError`.
2. `weight_kg` must be > 0, otherwise raise `ValueError`.
3. Every started kilogram above the first adds 2.00 (1.0 kg → +0, 1.2 kg → +2, 3.0 kg → +4, 3.1 kg → +6).
4. Express shipping doubles the total.
5. Domestic, non-express parcels of at most 0.5 kg ship free (0.00).
6. Round the result to 2 decimals.

Add thorough tests in `test_shipping.py` (pytest).
