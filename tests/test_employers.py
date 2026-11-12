import unittest

from jobpipe.employers import TIERS, Employer, employer_of


class EmployerTest(unittest.TestCase):
    def test_names_employers_publish_under(self):
        cases = {
            "Google Switzerland GmbH": Employer("Google", "faang"),
            "Google DeepMind": Employer("Google", "faang"),
            "Amazon Development Center (Romania) S.R.L.": Employer("Amazon", "faang"),
            "Amazon Web Services EMEA SARL": Employer("Amazon", "faang"),
            "Microsoft Schweiz GmbH": Employer("Microsoft", "faang"),
            "Meta": Employer("Meta", "faang"),
            "datadog": Employer("Datadog", "big_tech"),  # a board slug
            "Stripe, Inc.": Employer("Stripe", "big_tech"),
            "Booking.com": Employer("Booking.com", "big_tech"),
            "Wise Payments Ltd": Employer("Wise", "big_tech"),
            "hubspotjobs": Employer("HubSpot", "big_tech"),  # board slugs that are not the name
            "traderepublicbank": Employer("Trade Republic", "big_tech"),
            "Trade Republic Bank GmbH": Employer("Trade Republic", "big_tech"),
        }
        for company, expected in cases.items():
            with self.subTest(company=company):
                self.assertEqual(employer_of(company), expected)

    def test_similar_names_are_other_companies(self):
        for company in ["Elastic Path", "Metaview", "Apple Leisure Group", "Acme AG", "", None]:
            with self.subTest(company=company):
                self.assertEqual(employer_of(company), Employer(None, "other"))

    def test_every_tier_has_both_labels(self):
        self.assertEqual([t.key for t in TIERS], ["faang", "big_tech", "other"])
        for tier in TIERS:
            self.assertTrue(tier.label("en") and tier.label("es"))


if __name__ == "__main__":
    unittest.main()
