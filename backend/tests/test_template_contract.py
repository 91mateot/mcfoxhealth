"""Static API contract checks for routes declared in the SAM template."""

import re
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "template.yaml"


def test_api_function_exposes_rest_day_route():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    api_function = template.split("\n  ApiFunction:", 1)[1].split(
        "\n  NutritionFunction:", 1
    )[0]

    route = re.compile(
        r"^        MarkRestDay:\n"
        r"          Type: HttpApi\n"
        r"          Properties:\n"
        r"            ApiId: !Ref HttpApi\n"
        r"            Path: /api/planned-workout/rest\n"
        r"            Method: POST$",
        re.MULTILINE,
    )

    assert route.search(api_function), (
        "ApiFunction must expose POST /api/planned-workout/rest"
    )


def test_ingest_schedules_explicit_oauth_and_hevy_actions():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    ingest_function = template.split("\n  IngestFunction:", 1)[1].split(
        "\n  ComputeFunction:", 1
    )[0]

    assert "Schedule: cron(30 8 * * ? *)" in ingest_function
    assert "Input: '{\"action\":\"hevy_poll\"}'" in ingest_function
    assert "Schedule: cron(0 8 * * ? *)" in ingest_function
    assert "Input: '{\"action\":\"oauth_credential_check\"}'" in ingest_function


def test_http_api_access_logs_include_byte_volume_for_pre_lambda_413_diagnosis():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    http_api = template.split("\n  HttpApi:", 1)[1].split(
        "\n  # ── DynamoDB Tables", 1
    )[0]

    assert '"dataProcessed":"$context.dataProcessed"' in http_api
