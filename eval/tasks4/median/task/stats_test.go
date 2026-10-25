package stats

import "testing"

func TestEmpty(t *testing.T) {
	if _, err := Median(nil); err == nil {
		t.Fatal("expected error")
	}
}

func TestSingle(t *testing.T) {
	if m, _ := Median([]float64{7}); m != 7 {
		t.Fatalf("got %v", m)
	}
}
