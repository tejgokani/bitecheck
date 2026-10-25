package backoff

import (
	"testing"
	"time"
)

func TestHidden(t *testing.T) {
	ms := time.Millisecond
	cases := []struct {
		a         int
		base, max time.Duration
		want      time.Duration
	}{
		{1, 100 * ms, 10 * time.Second, 100 * ms}, {2, 100 * ms, 10 * time.Second, 200 * ms},
		{4, 100 * ms, 10 * time.Second, 800 * ms}, {0, 100 * ms, time.Second, 0}, {-3, 100 * ms, time.Second, 0},
		{5, 100 * ms, time.Second, time.Second}, {200, 100 * ms, time.Second, time.Second},
		{3, 0, time.Second, 0}, {3, -ms, time.Second, 0}, {3, ms, 0, 0}, {4, 300 * ms, time.Second, time.Second}, {1, 2 * time.Second, time.Second, time.Second},
	}
	for _, c := range cases {
		if got := Delay(c.a, c.base, c.max); got != c.want {
			t.Errorf("Delay(%d,%v,%v)=%v want %v", c.a, c.base, c.max, got, c.want)
		}
	}
}
