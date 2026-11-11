import unittest

from jobpipe.places import Place, country_code, parse


class ParseTest(unittest.TestCase):
    def test_formats_seen_in_the_sources(self):
        cases = {
            ("Zürich, Zürich, Switzerland", "CH"): Place("Zurich", ("CH",)),
            ("Gland, VD, Switzerland", "ch"): Place("Gland", ("CH",)),
            ("New York, NY", "US"): Place("New York", ("US",)),
            ("Palo Alto, CA", "US"): Place("Palo Alto", ("US",)),  # CA is California here, not Canada
            ("Espoo", "Finland"): Place("Espoo", ("FI",)),
            ("Barcelona, Catalunya [Cataluña], Spain", "ES"): Place("Barcelona", ("ES",)),
            ("Saint-Mandé, IDF, France", "fr"): Place("Saint-Mandé", ("FR",)),
            ("Boston, Massachusetts, USA; New York, New York, USA", None): Place("Boston", ("US",)),
            ("London & San Francisco", None): Place("London", ("GB", "US")),
            ("Barcelona (HQ)", None): Place("Barcelona", ("ES",)),
            ("Germany (remote); Zurich", None): Place("Zurich", ("DE", "CH"), remote=True),
            ("Remote job", "ES"): Place(None, ("ES",), remote=True),
            ("Colorado, USA, Remote", None): Place(None, ("US",), remote=True),
            ("Remote - US", None): Place(None, ("US",), remote=True),
            ("München", None): Place("Munich", ("DE",)),
            ("Somewhere", None): Place(None, ()),
            (None, None): Place(None, ()),
        }
        for (location, country), expected in cases.items():
            with self.subTest(location=location, country=country):
                self.assertEqual(parse(location, country), expected)

    def test_a_country_named_in_the_text_wins_over_a_city(self):
        self.assertEqual(parse("London, Ontario, Canada").countries, ("CA",))

    def test_known_cities_only_for_free_text(self):
        header = "Acme | Senior Engineer | Zurich, Switzerland | Onsite"

        self.assertEqual(parse(header, known_cities_only=True), Place("Zurich", ("CH",)))
        self.assertEqual(parse("Acme Labs | Engineer", known_cities_only=True).city, None)

    def test_country_field(self):
        self.assertEqual([country_code(v) for v in ["ch", "US", "uk", "Finland", "NAMER", "", None]],
                         ["CH", "US", "GB", "FI", None, None, None])  # fmt: skip


if __name__ == "__main__":
    unittest.main()
