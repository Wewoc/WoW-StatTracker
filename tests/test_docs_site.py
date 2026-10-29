# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# The GitHub Pages landing page (docs/index.html): every image exists, both languages are
# complete, nothing is loaded from a third party, and no screenshot is a stray file.

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
HTML = (DOCS / "index.html").read_text(encoding="utf-8")
IMAGES = sorted(p.name for p in (DOCS / "images").glob("*.png"))


def test_every_referenced_image_exists_and_every_image_is_used():
    referenced = set(re.findall(r'src="images/([^"]+)"', HTML))
    assert referenced, "no images referenced"
    assert referenced == set(IMAGES), (referenced ^ set(IMAGES))


def test_every_image_exists_in_both_languages():
    for name in IMAGES:
        stem, lang = name[:-4].rsplit("-", 1)
        other = "de" if lang == "en" else "en"
        assert f"{stem}-{other}.png" in IMAGES, name


def test_images_have_alt_text_and_size():
    for tag in re.findall(r"<img\b[^>]*>", HTML):
        assert re.search(r'\balt="[^"]{10,}"', tag), tag
        assert 'width="' in tag and 'height="' in tag, tag


def test_nothing_is_loaded_from_a_third_party():
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', HTML)
    assert urls, "expected the GitHub links"
    assert all(u.startswith("https://github.com/Wewoc/WoW-StatTracker") for u in urls), urls
    assert "<script src" not in HTML and "<link rel=\"stylesheet\"" not in HTML


def test_both_language_versions_of_each_text_exist():
    en = len(re.findall(r'class="(?:l )?en"', HTML))
    de = len(re.findall(r'class="(?:l )?de"', HTML))
    img_en = len(re.findall(r'class="shot en"', HTML))
    img_de = len(re.findall(r'class="shot de"', HTML))
    assert en and en == de, (en, de)
    assert img_en == img_de


def test_the_page_says_the_data_is_invented():
    assert "invented demo data" in HTML and "erfundene Demodaten" in HTML
