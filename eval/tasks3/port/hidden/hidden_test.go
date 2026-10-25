package port

import "testing"

func TestHidden(t *testing.T) {
	for _, ok := range []string{"1", "80", "65535"} {
		if _, err := ParsePort(ok); err != nil {
			t.Errorf("%s: %v", ok, err)
		}
	}
	for _, bad := range []string{"0", "-5", "65536", "70000", "x"} {
		if _, err := ParsePort(bad); err == nil {
			t.Errorf("%s accepted", bad)
		}
	}
}
