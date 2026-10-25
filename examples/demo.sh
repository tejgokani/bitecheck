#!/usr/bin/env bash
# bitecheck demo: an "agent" adds a feature, writes tests that look fine, and
# claims comprehensive coverage. bitecheck breaks the changed lines on purpose
# and shows which breaks no test notices.
# Needs: git, python3 with pytest, bitecheck on PATH. Leaves nothing behind.
set -euo pipefail

PY="${PYTHON:-python3}"
"$PY" -m pytest --version >/dev/null 2>&1 || { echo "demo needs pytest: $PY -m pip install pytest" >&2; exit 2; }
command -v bitecheck >/dev/null || { echo "demo needs bitecheck on PATH" >&2; exit 2; }

dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
cd "$dir"
git init -q -b main
git config user.email demo@example.com
git config user.name demo

cat > cart.py <<'PY'
def subtotal(items):
    return sum(price * qty for price, qty in items)
PY
cat > test_cart.py <<'PY'
from cart import subtotal


def test_subtotal():
    assert subtotal([(2, 3), (5, 1)]) == 11
PY
printf '__pycache__/\n' > .gitignore
git add -A && git commit -qm "cart"

# --- what the agent did ---------------------------------------------------------
cat > cart.py <<'PY'
def subtotal(items):
    return sum(price * qty for price, qty in items)


def total(items, coupon=None, member=False):
    amount = subtotal(items)
    if coupon == "HALF":
        amount = amount / 2
    elif coupon == "TENOFF" and amount >= 10:
        amount -= 10
    if member:
        amount *= 0.95
    return round(max(amount, 0), 2)
PY
cat >> test_cart.py <<'PY'


def test_total_without_coupon():
    from cart import total
    assert total([(2, 3)]) == 6


def test_total_with_coupons():
    from cart import total
    assert total([(2, 3)], "HALF") > 0
    assert total([(20, 1)], "TENOFF") < 20
PY
MSG="Added total() with coupon and member discounts. I added comprehensive tests and all tests pass."

echo "\$ git diff --stat"
git --no-pager diff --stat
echo
echo "\$ pytest -q"
"$PY" -m pytest -q -p no:cacheprovider | tail -1
echo
echo "agent: \"$MSG\""
echo
echo "\$ bitecheck --message \"...\""
NO_COLOR=${NO_COLOR:-} bitecheck -q --cmd "$PY -m pytest -q -p no:cacheprovider" --message "$MSG" || true
