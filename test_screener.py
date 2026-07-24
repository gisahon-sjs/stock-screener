"""Regression tests for the scoring/classification logic. Run: python test_screener.py"""
import unittest

import pandas as pd

import market_signals
import news_signals
import screener


class TestHeadlineClassifier(unittest.TestCase):
    def test_positive_deal_headline_scores_high(self):
        prob, label = news_signals.score_headline(
            "Company A to acquire Company B in all-cash deal at a premium")
        self.assertGreaterEqual(prob, 70)
        self.assertEqual(label, "호재 가능성 높음")

    def test_dead_deal_headline_scores_low(self):
        # Regression: this used to score as a positive catalyst just for
        # containing the word "merger".
        prob, label = news_signals.score_headline(
            "Destination XL Board Says FullBeauty Merger Is No Longer Advisable")
        self.assertLess(prob, 50)
        self.assertEqual(label, "악재 가능성")

    def test_terminated_merger_scores_low(self):
        prob, _ = news_signals.score_headline(
            "Company X terminates merger agreement with Company Y")
        self.assertLess(prob, 50)

    def test_unrelated_headline_is_neutral(self):
        prob, _ = news_signals.score_headline(
            "XCF Global director reports 1.17M-share restricted stock unit position")
        self.assertEqual(prob, 50)

    def test_empty_title_is_neutral(self):
        prob, label = news_signals.score_headline("")
        self.assertEqual(prob, 50)
        self.assertEqual(label, "중립")


class TestScoreRow(unittest.TestCase):
    def _row(self, **overrides):
        base = {
            "symbol": "TEST", "volume_ratio": None, "day_change_pct": None,
            "market_cap": None,
        }
        base.update(overrides)
        return base

    def test_no_signals_scores_zero(self):
        score, reasons = screener.score_row(self._row(), {}, {}, {})
        self.assertEqual(score, 0.0)
        self.assertEqual(reasons, [])

    def test_microcap_bonus_requires_existing_signal(self):
        # A micro-cap with literally nothing else going on should NOT score
        # above zero just for being small -- that was the bug that made
        # ~450/723 candidates score >0 with pure noise.
        row = self._row(market_cap=10_000_000)
        score, _ = screener.score_row(row, {}, {}, {})
        self.assertEqual(score, 0.0)

    def test_microcap_bonus_applies_on_top_of_existing_signal(self):
        row = self._row(market_cap=10_000_000, day_change_pct=20.0)
        score_with, _ = screener.score_row(row, {}, {}, {})
        row_no_mcap = self._row(market_cap=None, day_change_pct=20.0)
        score_without, _ = screener.score_row(row_no_mcap, {}, {}, {})
        self.assertGreater(score_with, score_without)

    def test_sec_hit_scores_positive(self):
        sec_hits = {"TEST": [{"keyword": "reverse merger", "form": "8-K", "file_date": "2026-01-01"}]}
        score, reasons = screener.score_row(self._row(), sec_hits, {}, {})
        self.assertGreaterEqual(score, 40)
        self.assertTrue(any("SEC 공시" in r for r in reasons))

    def test_bottom_reversal_scores_positive(self):
        row = self._row(bottom_reversal={
            "range_pos_pct": 12.0, "days_since_trough": 20, "base_days": 25,
            "breakout_pct": 15.0, "low_26w": 0.2, "high_26w": 0.9,
        })
        score, reasons = screener.score_row(row, {}, {}, {})
        self.assertGreater(score, 0)
        self.assertTrue(any("26주 바닥권" in r for r in reasons))

    def test_no_bottom_reversal_key_does_not_crash(self):
        row = self._row()  # no 'bottom_reversal' key at all
        score, _ = screener.score_row(row, {}, {}, {})
        self.assertEqual(score, 0.0)

    def test_nan_bottom_reversal_does_not_crash(self):
        # Regression: pandas left-merge fills unmatched rows with NaN (a float),
        # and `if reversal:` treated that truthy NaN as a real dict -> crash.
        row = self._row(bottom_reversal=float("nan"))
        score, _ = screener.score_row(row, {}, {}, {})
        self.assertEqual(score, 0.0)

    def test_sec_item_2_01_scores_higher_than_no_item(self):
        base = {"keyword": "reverse merger", "form": "8-K", "file_date": "2026-01-01"}
        sec_hits_plain = {"TEST": [dict(base)]}
        sec_hits_item = {"TEST": [dict(base, items=["2.01"])]}
        score_plain, _ = screener.score_row(self._row(), sec_hits_plain, {}, {})
        score_item, reasons_item = screener.score_row(self._row(), sec_hits_item, {}, {})
        self.assertGreater(score_item, score_plain)
        self.assertTrue(any("Item 2.01" in r for r in reasons_item))

    def test_positive_news_increases_score(self):
        news_hits = {"TEST": [{"title": "Company to acquire TEST in all-cash premium deal",
                                "catalyst_prob": 80, "catalyst_label": "호재 가능성 높음", "link": None}]}
        score, _ = screener.score_row(self._row(), {}, news_hits, {})
        self.assertGreater(score, 0)

    def test_negative_news_does_not_boost_score(self):
        # Regression: dead-deal news used to add a flat +25 just for matching
        # the keyword search, inflating the score for bad news.
        news_hits = {"TEST": [{"title": "TEST terminates merger agreement, deal collapses",
                                "catalyst_prob": 15, "catalyst_label": "악재 가능성", "link": None}]}
        score, _ = screener.score_row(self._row(), {}, news_hits, {})
        self.assertEqual(score, 0.0)  # clamped at zero, never goes negative

    def test_low_float_tiers(self):
        row_very_low = self._row(day_change_pct=20.0)
        score_base, _ = screener.score_row(row_very_low, {}, {}, {})
        score_vlow, _ = screener.score_row(row_very_low, {}, {}, {"TEST": {"float_shares": 3_000_000}})
        score_low, _ = screener.score_row(row_very_low, {}, {}, {"TEST": {"float_shares": 15_000_000}})
        self.assertGreater(score_vlow, score_low)
        self.assertGreater(score_low, score_base)

    def test_score_never_negative(self):
        news_hits = {"TEST": [{"title": "Deal terminated, merger collapses, lawsuit filed",
                                "catalyst_prob": 5, "catalyst_label": "악재 가능성", "link": None}]}
        score, _ = screener.score_row(self._row(), {}, news_hits, {})
        self.assertGreaterEqual(score, 0.0)


class TestBottomReversal(unittest.TestCase):
    def test_decline_base_breakout_detected(self):
        decline = pd.Series([10 - i * 0.08 for i in range(100)])  # 10 -> ~2
        sideways = pd.Series([2 + 0.10 * ((i % 4) - 1.5) for i in range(40)])
        breakout = pd.Series([2.2, 2.35, 2.5, 2.6, 2.7])
        closes = pd.concat([decline, sideways, breakout], ignore_index=True)
        result = market_signals.detect_bottom_reversal(closes)
        self.assertIsNotNone(result)
        self.assertLessEqual(result["range_pos_pct"], 25)
        self.assertGreater(result["breakout_pct"], 0)

    def test_pure_decline_not_detected(self):
        closes = pd.Series([10 - i * 0.05 for i in range(150)])
        self.assertIsNone(market_signals.detect_bottom_reversal(closes))

    def test_near_high_not_detected(self):
        rise = pd.Series([2 + i * 0.08 for i in range(100)])
        sideways = pd.Series([10 + 0.1 * ((i % 4) - 1.5) for i in range(40)])
        recent = pd.Series([9.5, 9.8, 10.1, 10.3, 10.5])
        closes = pd.concat([rise, sideways, recent], ignore_index=True)
        self.assertIsNone(market_signals.detect_bottom_reversal(closes))

    def test_insufficient_history_returns_none(self):
        closes = pd.Series([1.0, 1.1, 1.2, 0.9])
        self.assertIsNone(market_signals.detect_bottom_reversal(closes))


class TestKrCount(unittest.TestCase):
    def test_millions(self):
        self.assertEqual(screener.kr_count(5_400_000), "540만")

    def test_hundred_millions(self):
        self.assertEqual(screener.kr_count(142_000_000), "1억 4,200만")

    def test_small_number(self):
        self.assertEqual(screener.kr_count(3_000), "3,000")

    def test_exact_eok(self):
        self.assertEqual(screener.kr_count(300_000_000), "3억")


if __name__ == "__main__":
    unittest.main(verbosity=2)
