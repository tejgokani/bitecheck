class InsufficientStock(Exception):
    pass


class Inventory:
    def __init__(self):
        self._stock = {}
        self._reserved = {}

    def restock(self, item, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._stock[item] = self._stock.get(item, 0) + qty

    def available(self, item):
        return self._stock.get(item, 0) - self._reserved.get(item, 0)

    def reserve(self, item, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._reserved[item] = self._reserved.get(item, 0) + qty
        if self.available(item) < 0:
            raise InsufficientStock(item)
