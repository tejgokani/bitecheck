package backoff

import "time"

func Delay(attempt int, base, max time.Duration) time.Duration {
	if attempt < 1 || max <= 0 {
		return 0
	}
	d := base
	for i := 1; i < attempt; i++ {
		if d > max/2 { // 2d would exceed max (max/2 truncates)
			return max
		}
		d *= 2
	}
	if d > max {
		return max
	}
	return d
}
