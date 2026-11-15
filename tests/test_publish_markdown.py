from publish_markdown import render_markdown


def no_links(_target):
    return None


def identity(target):
    return target


def test_raw_html_is_escaped():
    out = render_markdown("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>", identity)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<script" not in out
    assert "<img" not in out
    assert "&lt;img src=x onerror=alert(1)&gt;" in out


def test_disallowed_schemes_render_as_text():
    hrefs = {"a": "javascript:alert(1)", "b": "data:text/html,x", "c": "https://example.com"}
    out = render_markdown("[one](a) [two](b) [three](c)", lambda target: hrefs[target])
    assert "javascript:" not in out
    assert "data:" not in out
    assert "one" in out and "two" in out
    assert '<a href="https://example.com">three</a>' in out
    assert out.count("<a ") == 1
    autolink = render_markdown("<https://example.com/x> <javascript:alert(1)>", identity)
    assert '<a href="https://example.com/x">https://example.com/x</a>' in autolink
    assert "<a href=\"javascript" not in autolink


def test_resolver_none_renders_link_text():
    out = render_markdown("See [Secret](/ops/x.md) now.", no_links)
    assert out == "<p>See Secret now.</p>"
    assert "<a" not in out


def test_blocks():
    text = "\n".join(
        [
            "# Title",
            "",
            "## Part",
            "",
            "## Part",
            "",
            "First line",
            "second line.",
            "",
            "- one",
            "- two",
            "  - nested",
            "- three",
            "",
            "1. first",
            "2. second",
            "",
            "> quoted *text*",
            "",
            "---",
            "",
            "```python",
            "print('<b>')",
            "```",
            "",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
        ]
    )
    out = render_markdown(text, identity)
    assert '<h1 id="title">Title</h1>' in out
    assert '<h2 id="part">Part</h2>' in out
    assert '<h2 id="part-2">Part</h2>' in out
    assert "<p>First line\nsecond line.</p>" in out
    assert "<ul>\n<li>one</li>\n<li>two\n<ul>\n<li>nested</li>\n</ul></li>\n<li>three</li>\n</ul>" in out
    assert "<ol>\n<li>first</li>\n<li>second</li>\n</ol>" in out
    assert "<blockquote>\n<p>quoted <em>text</em></p>\n</blockquote>" in out
    assert "<hr>" in out
    assert '<pre><code class="language-python">print(&#x27;&lt;b&gt;&#x27;)\n</code></pre>' in out
    assert "<table>\n<thead><tr><th>A</th><th>B</th></tr></thead>\n<tbody>\n<tr><td>1</td><td>2</td></tr>" in out


def test_fence_info_word_must_be_safe():
    out = render_markdown('```"><x\ncode\n```', identity)
    assert "class=" not in out
    assert "<pre><code>code\n</code></pre>" in out


def test_footnotes():
    out = render_markdown("Claim.[^s1] Other.[^zz]\n\n[^s1]: Source text", identity)
    assert '<sup class="fnref"><a href="#fn-s1" id="fnref-s1">1</a></sup>' in out
    assert '<section class="footnotes">' in out
    assert '<li id="fn-s1">Source text' in out
    assert "[^zz]" in out
    assert "[^s1]:" not in out


def test_inline():
    out = render_markdown("Use `**not bold**` and **b** and *i* ![alt <text>](pic.png)", identity)
    assert "<code>**not bold**</code>" in out
    assert "<strong>b</strong>" in out
    assert "<em>i</em>" in out
    assert "alt &lt;text&gt;" in out
    assert "<img" not in out
    assert "pic.png" not in out


def test_underscores_inside_words_are_not_emphasis():
    out = render_markdown("Set x_visibility_default and _real_ emphasis and __strong__.", identity)
    assert "x_visibility_default" in out
    assert "<em>real</em>" in out
    assert "<strong>strong</strong>" in out
    assert out.count("<em>") == 1
