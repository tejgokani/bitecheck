package text

// Truncate shortens s to at most n characters, replacing the cut part with "…".
func Truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}
