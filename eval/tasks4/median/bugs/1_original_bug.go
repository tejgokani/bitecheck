package stats

import "errors"

// Median returns the median of xs.
func Median(xs []float64) (float64, error) {
	if len(xs) == 0 {
		return 0, errors.New("empty input")
	}
	return xs[len(xs)/2], nil
}
