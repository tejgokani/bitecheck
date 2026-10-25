package text

import "testing"

func TestShortStringUnchanged(t *testing.T) {
	if got := Truncate("hi", 5); got != "hi" {
		t.Fatalf("got %q", got)
	}
}
