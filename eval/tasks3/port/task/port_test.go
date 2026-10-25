package port

import "testing"

func TestParsesNumber(t *testing.T) {
	n, err := ParsePort("8080")
	if err != nil || n != 8080 {
		t.Fatalf("got %d, %v", n, err)
	}
}

func TestRejectsText(t *testing.T) {
	if _, err := ParsePort("http"); err == nil {
		t.Fatal("expected error")
	}
}
