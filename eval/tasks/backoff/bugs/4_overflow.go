package backoff

import "time"

func Delay(attempt int, base, max time.Duration) time.Duration {
	if attempt < 1 || base <= 0 || max <= 0 {
		return 0
	}
	d := base
	for i := 1; i < attempt; i++ {
		d *= 2
	}
	if d > max {
		return max
	}
	return d
}
