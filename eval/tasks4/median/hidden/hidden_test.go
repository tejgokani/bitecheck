package stats

import "testing"

func TestHidden(t *testing.T) {
	in := []float64{3, 1, 2, 4}
	if m, err := Median(in); err != nil || m != 2.5 {
		t.Fatalf("got %v %v", m, err)
	}
	if in[0] != 3 || in[1] != 1 {
		t.Fatal("input reordered")
	}
	if m, _ := Median([]float64{5, 1, 3}); m != 3 {
		t.Fatalf("odd: %v", m)
	}
	if m, _ := Median([]float64{10, 2}); m != 6 {
		t.Fatalf("pair: %v", m)
	}
}
