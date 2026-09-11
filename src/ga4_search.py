from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    OrderBy,
    RunReportRequest,
)

from src.ga4_auth import get_credentials
from src.privacy_filter import (
    is_safe_search_term,
    normalize_search_term,
)


GA4_PROPERTY_ID = "396295106"
SEARCH_DIMENSION = "customEvent:ep_search_searchword"
SEARCH_METRIC = "screenPageViews"
MAX_ROWS = 100_000


def _exact_filter(
    field_name: str,
    value: str,
) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=value,
                case_sensitive=True,
            ),
        )
    )


def _and_filter(
    expressions: list[FilterExpression],
) -> FilterExpression:
    return FilterExpression(
        and_group=FilterExpressionList(
            expressions=expressions
        )
    )


def build_search_filter() -> FilterExpression:
    web = _and_filter(
        [
            _exact_filter("eventName", "page_view"),
            _exact_filter("platform", "web"),
        ]
    )

    android = _and_filter(
        [
            _exact_filter("eventName", "screen_view"),
            _exact_filter("platform", "Android"),
        ]
    )

    ios = _and_filter(
        [
            _exact_filter("eventName", "screen_view"),
            _exact_filter("platform", "iOS"),
        ]
    )

    return FilterExpression(
        or_group=FilterExpressionList(
            expressions=[web, android, ios]
        )
    )


def _client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(
        credentials=get_credentials()
    )


def fetch_search_terms(
    target_date: str,
    limit: int = MAX_ROWS,
) -> list[dict]:
    """Fetch safe search terms for one date, ordered by search views."""
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name=SEARCH_DIMENSION)],
        metrics=[Metric(name=SEARCH_METRIC)],
        date_ranges=[
            DateRange(
                start_date=target_date,
                end_date=target_date,
            )
        ],
        dimension_filter=build_search_filter(),
        order_bys=[
            OrderBy(
                metric=OrderBy.MetricOrderBy(
                    metric_name=SEARCH_METRIC
                ),
                desc=True,
            )
        ],
        limit=min(limit, MAX_ROWS),
    )

    response = _client().run_report(request=request)

    rows = []

    for row in response.rows:
        search_term = normalize_search_term(
            row.dimension_values[0].value
        )
        views = int(row.metric_values[0].value or 0)

        if not is_safe_search_term(search_term):
            continue

        rows.append(
            {
                "search_term": search_term,
                "views": views,
            }
        )

    return rows


def comparison_dates(
    target_date: date,
    compare_mode: str,
    custom_date: date | None = None,
) -> list[date]:
    if compare_mode == "전일":
        return [target_date - timedelta(days=1)]

    if compare_mode == "전주":
        return [target_date - timedelta(days=7)]

    if compare_mode == "4주평균":
        return [
            target_date - timedelta(days=7 * week)
            for week in range(1, 5)
        ]

    if compare_mode == "Custom Date":
        if custom_date is None:
            raise ValueError("Custom Date를 선택해주세요.")
        return [custom_date]

    raise ValueError(f"지원하지 않는 비교 기준입니다: {compare_mode}")


def aggregate_average(
    datasets: Iterable[list[dict]],
) -> list[dict]:
    datasets = list(datasets)

    if not datasets:
        return []

    totals: dict[str, float] = defaultdict(float)

    for rows in datasets:
        current = {
            row["search_term"]: float(row["views"])
            for row in rows
        }

        for term in set(totals) | set(current):
            totals[term] += current.get(term, 0.0)

    divisor = len(datasets)

    result = [
        {
            "search_term": term,
            "views": value / divisor,
        }
        for term, value in totals.items()
    ]

    result.sort(
        key=lambda row: row["views"],
        reverse=True,
    )

    return result
