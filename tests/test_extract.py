import extract


def test_extract_from_html_strips_boilerplate():
    html = """<html><head><title>x</title></head><body>
      <nav>menu menu menu</nav>
      <main><p>The committee will keep rates restrictive.</p>
      <p>Inflation remains elevated.</p></main>
      <script>var x=1;</script>
      <footer>copyright</footer></body></html>"""
    text = extract.extract_from_html(html)
    assert "rates restrictive" in text
    assert "Inflation remains elevated" in text
    assert "var x=1" not in text
    assert "menu menu menu" not in text


def test_extract_text_routes_pdf_vs_html(monkeypatch):
    class FakeResp:
        def __init__(self, ctype, body):
            self.headers = {"content-type": ctype}
            self.content = body
            self.text = body.decode() if isinstance(body, bytes) else body

        def raise_for_status(self):
            pass

    monkeypatch.setattr(extract, "extract_from_html", lambda h: "HTML")
    monkeypatch.setattr(extract, "extract_from_pdf", lambda b: "PDF")

    monkeypatch.setattr(extract.httpx, "get",
                        lambda *a, **k: FakeResp("text/html; charset=utf-8", "<p>hi</p>"))
    assert extract.extract_text("https://x/a.htm") == "HTML"

    monkeypatch.setattr(extract.httpx, "get",
                        lambda *a, **k: FakeResp("application/pdf", b"%PDF-1.4"))
    assert extract.extract_text("https://x/a.pdf") == "PDF"


def test_extract_text_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(extract.httpx, "get", boom)
    assert extract.extract_text("https://x/a") is None
