package text

import (
	"testing"
	"unicode/utf8"
)

func TestHidden(t *testing.T) {
	cases := map[[2]any]string{
		{"héllo", 5}: "héllo", {"héllo wörld", 5}: "héll…", {"abcdef", 3}: "ab…", {"abc", 3}: "abc", {"abc", 0}: "",
		{"日本語テキスト", 4}: "日本語…",
	}
	for in, want := range cases {
		got := Truncate(in[0].(string), in[1].(int))
		if got != want || !utf8.ValidString(got) {
			t.Errorf("Truncate(%q,%d)=%q want %q", in[0], in[1], got, want)
		}
	}
}
