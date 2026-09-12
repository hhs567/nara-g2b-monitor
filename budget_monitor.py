def get_budget_source(local_name):

    local_name = normalize_local_name(
        local_name
    )

    source = budget_sources.get(
        local_name
    )

    # --------------------------------------------------------
    # 75개 대상 지자체에 등록되어 있는 경우
    # --------------------------------------------------------

    if source:

        source_url = source.get(
            "source_url",
            ""
        )

        if source_url:

            status = "공식 예산서 게시판 확인 가능"

        else:

            status = (
                "공식 예산서 URL 확인 중 "
                "→ 지방재정365 자료 사용"
            )

        return {
            "available": True,
            "region": source.get(
                "region",
                ""
            ),
            "source_name": source.get(
                "source_name",
                f"{local_name} 공식 예산정보"
            ),
            "source_url": source_url,
            "latest_budget_title": source.get(
                "latest_budget_title",
                ""
            ),
            "latest_budget_date": source.get(
                "latest_budget_date",
                ""
            ),
            "status": status,
        }

    # --------------------------------------------------------
    # 혹시 명칭이 매칭되지 않은 경우
    # --------------------------------------------------------

    return {
        "available": False,
        "region": "",
        "source_name": (
            "지방재정365 세부사업별 세출현황"
        ),
        "source_url": "",
        "latest_budget_title": "",
        "latest_budget_date": "",
        "status": "지방재정365 공식 데이터",
    }
