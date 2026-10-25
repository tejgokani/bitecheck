package port

import (
	"fmt"
	"strconv"
)

// ParsePort parses a TCP port number.
func ParsePort(s string) (int, error) {
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("invalid port %q: %w", s, err)
	}
	return n, nil
}
