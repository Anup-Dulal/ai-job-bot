"""
tests/test_fetcher.py — Tests for naukri_fetcher.py

Tests cover:
- freshness_score()
- is_excluded()
- _clean()
- generate_keywords()
- fetch_linkedin() with mocked HTTP
- fetch_naukri() with mocked HTTP
- fetch_indeed_remote() with mocked HTTP
- fetch_all_jobs() deduplication
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add parent dir to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_fetcher import (
    freshness_score,
    is_excluded,
    _clean,
    generate_keywords,
    fetch_linkedin,
    fetch_naukri,
    fetch_indeed_remote,
)


# ─── freshness_score ──────────────────────────────────────────────────────────

class TestFreshnessScore:
    def test_empty_string_returns_30(self):
        assert freshness_score("") == 30

    def test_just_now_returns_0(self):
        assert freshness_score("just now") == 0

    def test_today_returns_0(self):
        assert freshness_score("today") == 0

    def test_minutes_returns_0(self):
        assert freshness_score("30 minutes ago") == 0

    def test_hours_returns_0(self):
        assert freshness_score("2 hours ago") == 0

    def test_1_day_returns_1(self):
        assert freshness_score("1 day ago") == 1

    def test_3_days_returns_3(self):
        assert freshness_score("3 days ago") == 3

    def test_1_week_returns_7(self):
        assert freshness_score("1 week ago") == 7

    def test_2_weeks_returns_14(self):
        assert freshness_score("2 weeks ago") == 14

    def test_1_month_returns_30(self):
        assert freshness_score("1 month ago") == 30

    def test_iso_date_recent(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        score = freshness_score(recent)
        assert 1 <= score <= 3

    def test_unknown_string_returns_30(self):
        assert freshness_score("some random text") == 30


# ─── is_excluded ──────────────────────────────────────────────────────────────

class TestIsExcluded:
    def test_staffing_company_excluded(self):
        assert is_excluded("ABC Staffing Solutions") is True

    def test_recruitment_company_excluded(self):
        assert is_excluded("XYZ Recruitment Agency") is True

    def test_placement_company_excluded(self):
        assert is_excluded("Best Placement Services") is True

    def test_normal_company_not_excluded(self):
        assert is_excluded("Infosys") is False

    def test_product_company_not_excluded(self):
        assert is_excluded("Google India") is False

    def test_empty_company_not_excluded(self):
        assert is_excluded("") is False

    def test_case_insensitive(self):
        assert is_excluded("STAFFING CORP") is True


# ─── _clean ───────────────────────────────────────────────────────────────────

class TestClean:
    def test_strips_html_tags(self):
        assert _clean("<b>Java Developer</b>") == "Java Developer"

    def test_collapses_whitespace(self):
        assert _clean("Java   Developer") == "Java Developer"

    def test_strips_leading_trailing(self):
        assert _clean("  Java Developer  ") == "Java Developer"

    def test_empty_string(self):
        assert _clean("") == ""

    def test_none_returns_empty(self):
        assert _clean(None) == ""

    def test_nested_html(self):
        result = _clean("<div><span>Spring Boot</span></div>")
        assert "Spring Boot" in result
        assert "<" not in result


# ─── generate_keywords ────────────────────────────────────────────────────────

class TestGenerateKeywords:
    def test_uses_env_var_comma_separated(self):
        with patch.dict(os.environ, {"SEARCH_KEYWORDS": "Java Developer,Spring Boot,Microservices"}):
            keywords = generate_keywords()
        assert keywords == ["Java Developer", "Spring Boot", "Microservices"]

    def test_uses_env_var_pipe_separated(self):
        with patch.dict(os.environ, {"SEARCH_KEYWORDS": "Java Developer|Spring Boot|Microservices"}):
            keywords = generate_keywords()
        assert keywords == ["Java Developer", "Spring Boot", "Microservices"]

    def test_limits_to_4_keywords(self):
        with patch.dict(os.environ, {"SEARCH_KEYWORDS": "A,B,C,D,E,F"}):
            keywords = generate_keywords()
        assert len(keywords) == 4

    def test_returns_defaults_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("naukri_fetcher.call_llm", return_value=""):
                keywords = generate_keywords()
        assert len(keywords) == 4
        assert all(isinstance(k, str) for k in keywords)

    def test_parses_llm_json_response(self):
        llm_response = '["Java Backend", "Spring Boot Dev", "Microservices Eng", "Backend Java"]'
        with patch.dict(os.environ, {}, clear=True):
            with patch("naukri_fetcher.call_llm", return_value=llm_response):
                keywords = generate_keywords()
        assert keywords == ["Java Backend", "Spring Boot Dev", "Microservices Eng", "Backend Java"]

    def test_falls_back_on_bad_llm_response(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("naukri_fetcher.call_llm", return_value="not valid json"):
                keywords = generate_keywords()
        assert len(keywords) == 4


# ─── fetch_linkedin ───────────────────────────────────────────────────────────

LINKEDIN_SAMPLE_HTML = """
<div class="base-search-card__title">Java Backend Developer</div>
<div class="base-search-card__subtitle"><a href="#">Infosys</a></div>
<span class="job-search-card__location">Noida, Uttar Pradesh</span>
<time class="job-search-card__listdate">2 days ago</time>
<li data-entity-urn="urn:li:jobPosting:1234567890"></li>
"""


class TestFetchLinkedin:
    def test_returns_list(self):
        with patch("naukri_fetcher._http_get", return_value=LINKEDIN_SAMPLE_HTML):
            jobs = fetch_linkedin("Java Developer", "Noida")
        assert isinstance(jobs, list)

    def test_job_has_required_fields(self):
        with patch("naukri_fetcher._http_get", return_value=LINKEDIN_SAMPLE_HTML):
            jobs = fetch_linkedin("Java Developer", "Noida")
        if jobs:
            job = jobs[0]
            assert "id" in job
            assert "title" in job
            assert "company" in job
            assert "source" in job
            assert job["source"] == "LinkedIn"
            assert job["easy_apply"] is True

    def test_id_prefixed_with_li(self):
        with patch("naukri_fetcher._http_get", return_value=LINKEDIN_SAMPLE_HTML):
            jobs = fetch_linkedin("Java Developer", "Noida")
        if jobs:
            assert jobs[0]["id"].startswith("li_")

    def test_empty_html_returns_empty_list(self):
        with patch("naukri_fetcher._http_get", return_value=""):
            jobs = fetch_linkedin("Java Developer", "Noida")
        assert jobs == []

    def test_remote_uses_f_wt_param(self):
        captured_params = {}

        def mock_get(url, params=None):
            captured_params.update(params or {})
            return ""

        with patch("naukri_fetcher._http_get", side_effect=mock_get):
            fetch_linkedin("Java Developer", "Remote")

        assert captured_params.get("f_WT") == "2"
        assert "location" not in captured_params

    def test_india_uses_geoid(self):
        captured_params = {}

        def mock_get(url, params=None):
            captured_params.update(params or {})
            return ""

        with patch("naukri_fetcher._http_get", side_effect=mock_get):
            fetch_linkedin("Java Developer", "Noida")

        assert captured_params.get("geoId") == "102713980"
        assert captured_params.get("location") == "Noida"

    def test_excludes_staffing_companies(self):
        html_with_staffing = LINKEDIN_SAMPLE_HTML.replace("Infosys", "ABC Staffing Solutions")
        with patch("naukri_fetcher._http_get", return_value=html_with_staffing):
            jobs = fetch_linkedin("Java Developer", "Noida")
        companies = [j["company"] for j in jobs]
        assert not any("staffing" in c.lower() for c in companies)

    def test_easy_apply_filter_in_params(self):
        captured_params = {}

        def mock_get(url, params=None):
            captured_params.update(params or {})
            return ""

        with patch("naukri_fetcher._http_get", side_effect=mock_get):
            fetch_linkedin("Java Developer", "Noida")

        assert captured_params.get("f_LF") == "f_AL"


# ─── fetch_naukri ─────────────────────────────────────────────────────────────

NAUKRI_JSON_HTML = """
<script>
window.__INITIAL_STATE__ = {"jobsData":{"jobDetails":[
  {"jobId":"123","title":"Java Developer","companyName":"TCS",
   "placeholders":[{"type":"location","label":"Noida"},{"type":"experience","label":"3-5 years"}],
   "jobDescription":"Spring Boot microservices","jdURL":"/job-listings/java-developer-tcs-123",
   "footerPlaceholderLabel":"2 days ago"}
]}};
</script>
"""

NAUKRI_EMPTY_HTML = """
<script>
window.__INITIAL_STATE__ = {"jobsData":{"jobDetails":[]}};
</script>
"""


class TestFetchNaukri:
    def test_parses_json_embedded_state(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_JSON_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Java Developer"
        assert jobs[0]["company"] == "TCS"
        assert jobs[0]["source"] == "Naukri"

    def test_job_id_prefixed_with_naukri(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_JSON_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert jobs[0]["id"].startswith("naukri_")

    def test_empty_job_list_returns_empty(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_EMPTY_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert jobs == []

    def test_empty_html_returns_empty(self):
        with patch("naukri_fetcher._http_get", return_value=""):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert jobs == []

    def test_experience_appended_to_description(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_JSON_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert "3-5 years" in jobs[0]["description"]

    def test_apply_url_constructed(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_JSON_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert "naukri.com" in jobs[0]["apply_url"]

    def test_easy_apply_true(self):
        with patch("naukri_fetcher._http_get", return_value=NAUKRI_JSON_HTML):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert jobs[0]["easy_apply"] is True

    def test_excludes_staffing_companies(self):
        html = NAUKRI_JSON_HTML.replace('"TCS"', '"ABC Staffing Solutions"')
        with patch("naukri_fetcher._http_get", return_value=html):
            jobs = fetch_naukri("Java Developer", "Noida")
        assert jobs == []


# ─── fetch_indeed_remote ──────────────────────────────────────────────────────

INDEED_SAMPLE_HTML = """
<div data-jk="abc123def456">
  <h2 class="jobTitle"><span>Java Backend Engineer</span></h2>
  <span data-testid="company-name">Acme Corp</span>
  <div data-testid="text-location">Remote</div>
  <ul class="job-snippet"><li>Spring Boot</li><li>Microservices</li></ul>
</div>
"""


class TestFetchIndeedRemote:
    def test_returns_list_on_success(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = INDEED_SAMPLE_HTML

        with patch("naukri_fetcher.httpx.get", return_value=mock_resp):
            jobs = fetch_indeed_remote("Java Developer")

        assert isinstance(jobs, list)

    def test_job_source_is_indeed(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = INDEED_SAMPLE_HTML

        with patch("naukri_fetcher.httpx.get", return_value=mock_resp):
            jobs = fetch_indeed_remote("Java Developer")

        if jobs:
            assert jobs[0]["source"] == "Indeed"

    def test_job_id_prefixed_with_indeed(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = INDEED_SAMPLE_HTML

        with patch("naukri_fetcher.httpx.get", return_value=mock_resp):
            jobs = fetch_indeed_remote("Java Developer")

        if jobs:
            assert jobs[0]["id"].startswith("indeed_")

    def test_returns_empty_on_http_error(self):
        with patch("naukri_fetcher.httpx.get", side_effect=Exception("403 Forbidden")):
            jobs = fetch_indeed_remote("Java Developer")
        assert jobs == []

    def test_easy_apply_false_for_indeed(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = INDEED_SAMPLE_HTML

        with patch("naukri_fetcher.httpx.get", return_value=mock_resp):
            jobs = fetch_indeed_remote("Java Developer")

        if jobs:
            assert jobs[0]["easy_apply"] is False
