import unittest
from textwrap import dedent

from update_config import (
    Pair,
    ActionError,
    apply_updates,
    parse_list,
    parse_refs,
    update_image_line,
)

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


class ParseListTests(unittest.TestCase):
    def test_strips_and_drops_blanks(self):
        self.assertEqual(parse_list("a\n  b  \n\nc\n"), ["a", "b", "c"])

    def test_handles_crlf(self):
        self.assertEqual(parse_list("a\r\nb\r\n"), ["a", "b"])


class ParseRefsTests(unittest.TestCase):
    def test_empty_input(self):
        with self.assertRaisesRegex(ActionError, "No image references"):
            parse_refs("")

    def test_missing_at_sign(self):
        with self.assertRaisesRegex(ActionError, "missing '@'"):
            parse_refs("ghcr.io/foo")

    def test_empty_image_part(self):
        with self.assertRaisesRegex(ActionError, "empty image"):
            parse_refs(f"@{D1}")

    def test_invalid_digest(self):
        with self.assertRaisesRegex(ActionError, "Invalid digest"):
            parse_refs("img@not-a-digest")

    def test_rejects_short_digest(self):
        with self.assertRaisesRegex(ActionError, "Invalid digest"):
            parse_refs("img@sha256:abc")

    def test_ok_single(self):
        self.assertEqual(parse_refs(f"img@{D1}"), [Pair("img", D1)])

    def test_ok_multiple(self):
        self.assertEqual(
            parse_refs(f"a@{D1}\nb@{D2}\n"),
            [Pair("a", D1), Pair("b", D2)],
        )


class UpdateImageLineTests(unittest.TestCase):
    def test_replaces_tag_form(self):
        config = '  - image: "ghcr.io/x/y:v1.0.0" # v1.0.0\n'
        out = update_image_line(config, Pair("ghcr.io/x/y", D2), "v2.0.0")
        self.assertEqual(out, f'  - image: "ghcr.io/x/y@{D2}" # v2.0.0\n')

    def test_replaces_digest_form(self):
        config = f'image: "ghcr.io/x/y@{D1}" # v1.0.0\n'
        out = update_image_line(config, Pair("ghcr.io/x/y", D2), "v2.0.0")
        self.assertEqual(out, f'image: "ghcr.io/x/y@{D2}" # v2.0.0\n')

    def test_preserves_indent(self):
        config = '      image: "ghcr.io/x/y:old" # v1\n'
        out = update_image_line(config, Pair("ghcr.io/x/y", D1), "v2")
        self.assertEqual(out, f'      image: "ghcr.io/x/y@{D1}" # v2\n')

    def test_no_match_raises(self):
        with self.assertRaisesRegex(ActionError, "Could not find"):
            update_image_line("nothing here\n", Pair("ghcr.io/x/y", D1), "v1")

    def test_idempotent_when_already_pinned(self):
        # Re-applying the digest/version already in the file is a no-op. The
        # action relies on this: `git diff` then reports no change, no PR.
        config = f'image: "ghcr.io/x/y@{D1}" # v1.0.0\n'
        out = update_image_line(config, Pair("ghcr.io/x/y", D1), "v1.0.0")
        self.assertEqual(out, config)

    def test_does_not_match_other_image_with_shared_prefix(self):
        config = (
            'image: "ghcr.io/x/y-extra:v1" # v1\n'
            'image: "ghcr.io/x/y:v1" # v1\n'
        )
        out = update_image_line(config, Pair("ghcr.io/x/y", D1), "v2")
        self.assertIn('ghcr.io/x/y-extra:v1', out)
        self.assertIn(f'image: "ghcr.io/x/y@{D1}" # v2', out)


class ApplyUpdatesTests(unittest.TestCase):
    def test_multiple_images(self):
        config = 'image: "x:old" # v0\nimage: "y:old" # v0\n'
        out = apply_updates(config, [Pair("x", D1), Pair("y", D2)], "v1")
        self.assertIn(f'image: "x@{D1}" # v1', out)
        self.assertIn(f'image: "y@{D2}" # v1', out)

    def test_full_config_file_byte_for_byte(self):
        # Real tinfoil-config.yml shape. The whole-file comparison verifies
        # every non-image line is preserved exactly — including the
        # shim-version line, which contains "@sha256:" but is NOT an image:
        # entry and must not be touched.
        before = dedent("""\
            shim-version: v0.3.18@sha256:7d9f98be78c91ede89f43c948a12d084fae34312effe9395ca7ed572991cb561
            cvm-version: 0.7.5
            cpus: 2
            memory: 8192

            containers:
              - name: “container-1”
                image: "ghcr.io/tinfoilsh/container-1@sha256:9a8171cb264007d87883f075b1e0816f9e0a5d7a522e6e2ddfff7fff5cf5c9fe" # v0.0.9
                user: "1000:1000"
                memory: "256m"
                cpus: 0.5

              - name: “container-2”
                image: "ghcr.io/tinfoilsh/container-2@sha256:c428fc1b81a1d5746999c2e9c1fcbe69ce007f7b04ccf5d26f855a8dcb434e3a" # v0.0.9
                user: "1000:1000"
                cpus: 2

            shim:
              upstream-port: 8000
              paths:
                - /health
        """)
        expected = dedent(f"""\
            shim-version: v0.3.18@sha256:7d9f98be78c91ede89f43c948a12d084fae34312effe9395ca7ed572991cb561
            cvm-version: 0.7.5
            cpus: 2
            memory: 8192

            containers:
              - name: “container-1”
                image: "ghcr.io/tinfoilsh/container-1@{D1}" # v0.1.0
                user: "1000:1000"
                memory: "256m"
                cpus: 0.5

              - name: “container-2”
                image: "ghcr.io/tinfoilsh/container-2@{D2}" # v0.1.0
                user: "1000:1000"
                cpus: 2

            shim:
              upstream-port: 8000
              paths:
                - /health
        """)
        pairs = [
            Pair("ghcr.io/tinfoilsh/container-1", D1),
            Pair("ghcr.io/tinfoilsh/container-2", D2),
        ]
        self.assertEqual(apply_updates(before, pairs, "v0.1.0"), expected)


    def test_idempotent_when_already_pinned(self):
        config = f'image: "x@{D1}" # v1\nimage: "y@{D2}" # v1\n'
        out = apply_updates(config, [Pair("x", D1), Pair("y", D2)], "v1")
        self.assertEqual(out, config)


if __name__ == "__main__":
    unittest.main()
