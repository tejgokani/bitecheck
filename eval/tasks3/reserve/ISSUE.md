Customers can reserve more units than we have in stock: reserving 10 apples when only 5 are available succeeds
and `available()` goes negative. `reserve` should raise `InsufficientStock` (and reserve nothing) when the
request exceeds what is available. Reserving exactly what is available is fine.
