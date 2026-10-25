`Median([]float64{3, 1, 2, 4})` returns 2 instead of 2.5: the input is not sorted, and for an even number of values the
median is the mean of the two middle values. `Median` must not reorder the caller's slice. Tests run with `go test ./...`.
