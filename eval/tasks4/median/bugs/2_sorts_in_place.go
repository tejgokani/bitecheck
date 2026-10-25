package stats

import (
	"errors"
	"sort"
)

// Median returns the median of xs.
func Median(xs []float64) (float64, error) {
	if len(xs) == 0 {
		return 0, errors.New("empty input")
	}
	s := xs
	sort.Float64s(s)
	mid := len(s) / 2
	if len(s)%2 == 0 {
		return (s[mid-1] + s[mid]) / 2, nil
	}
	return s[mid], nil
}
