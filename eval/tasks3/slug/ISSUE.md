`slugify("  Hello -- World! ")` returns `"--hello----world---"`. Slugs must not start or end with a dash, and
runs of separators must collapse into a single dash: the expected result is `"hello-world"`.
Tests run with `node --test`.
