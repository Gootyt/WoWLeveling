import unittest
import urllib.error
from decimal import Decimal
from unittest import mock

import murlok
from leveling import Character, SpecScores

# A Murlok.io rangsoroldalainak felépítését követő kivonat (az attribútumok sorrendje az
# oldalon is változik), kiegészítve olyan elemekkel, amelyeket figyelmen kívül kell hagyni.
RANKING_PAGE = """
<ul class="vi-box">
  <li>
    <a class="vi-box meta-item death-knight-color vi-box-without-padding" href="/death-knight/unholy/m+">
      <div class="vi-box vi-box-without-background">
        <div class="h3">13</div>
        <div>
          <div class="h3">Unholy Death Knight</div>
          <div class="vi-observer"><div class="vi-infobar"><div role="img"><div></div></div>
            <ul class="vi-box vi-box-with-columns">
              <li class="vi-media-object vi-media-object-with-media-small">
                <svg viewBox="0 0 24 24"><path fill="currentColor" d="M16,11.78L20.24,4.45Z" /></svg>
                3891
              </li>
            </ul>
          </div></div>
        </div>
      </div>
      <img alt="Unholy Death Knight Icon" src="https://render.worldofwarcraft.com/us/icons/56/135775.jpg">
    </a>
  </li>
  <li>
    <a href="/hunter/beast-mastery/m+" class="vi-box meta-item hunter-color">
      <div class="h3">14</div>
      <div class="h3">Beast Mastery Hunter</div>
      <ul><li class="vi-media-object vi-media-object-with-media-small"><svg></svg> 3,899 </li></ul>
      <img loading="lazy" alt="Beast Mastery Hunter Icon" src="https://render.worldofwarcraft.com/x.jpg">
    </a>
  </li>
  <li>
    <a class="vi-box meta-item mage-color" href="https://murlok.io/mage/frost/m+">
      <ul>
        <li class="vi-media-object">Új</li>
        <li class="vi-media-object">3712.5</li>
        <li class="vi-media-object">9999</li>
      </ul>
    </a>
  </li>
</ul>
<a class="vi-box" href="/death-knight/blood/m+"><ul><li class="vi-media-object">1234</li></ul></a>
<a class="vi-box meta-item" href="/about"><ul><li class="vi-media-object">999</li></ul></a>
"""

EMPTY_PAGE = "<html><body><p>Karbantartás</p></body></html>"


class ParseTests(unittest.TestCase):
    def test_reads_spec_scores_from_ranking_page(self):
        self.assertEqual(
            murlok.parse_meta_page(RANKING_PAGE),
            {
                "death knight/unholy": Decimal("3891"),
                "hunter/beast mastery": Decimal("3899"),
                "mage/frost": Decimal("3712.5"),
            },
        )

    def test_keys_match_character_class_and_spec(self):
        scores = SpecScores(murlok.parse_meta_page(RANKING_PAGE))
        self.assertEqual(scores.score_for(Character("Rexxar", "Hunter", "Beast Mastery")), Decimal("3899"))
        self.assertEqual(scores.score_for(Character("Arthas", "Death Knight", "Unholy")), Decimal("3891"))

    def test_page_without_rankings(self):
        self.assertEqual(murlok.parse_meta_page(EMPTY_PAGE), {})


class FetchTests(unittest.TestCase):
    def test_all_three_role_pages_are_merged(self):
        pages = {
            murlok.meta_url("tank"): RANKING_PAGE.replace("/death-knight/unholy/", "/death-knight/blood/"),
            murlok.meta_url("healer"): RANKING_PAGE.replace("/death-knight/unholy/", "/paladin/holy/"),
            murlok.meta_url("dps"): RANKING_PAGE,
        }
        with mock.patch.object(murlok, "fetch_page", side_effect=pages.__getitem__) as fetch_page:
            scores = murlok.fetch_spec_scores()
        self.assertEqual(sorted(call.args[0] for call in fetch_page.call_args_list), sorted(pages))
        self.assertEqual(
            {key: scores[key] for key in ("death knight/blood", "paladin/holy", "death knight/unholy")},
            {"death knight/blood": 3891, "paladin/holy": 3891, "death knight/unholy": 3891},
        )

    def test_page_without_rankings_is_an_error(self):
        with mock.patch.object(murlok, "fetch_page", return_value=EMPTY_PAGE):
            with self.assertRaisesRegex(murlok.MurlokError, "tank rangsorában nem találtam pontszámokat"):
                murlok.fetch_spec_scores()

    def test_network_errors_have_readable_messages(self):
        error = urllib.error.URLError("timed out")
        with mock.patch.object(murlok.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(murlok.MurlokError, r"nem érhető el \(timed out\)"):
                murlok.fetch_page(murlok.meta_url("dps"))

    def test_urls(self):
        self.assertEqual(murlok.meta_url("healer"), "https://murlok.io/meta/healer/m+")


if __name__ == "__main__":
    unittest.main()
