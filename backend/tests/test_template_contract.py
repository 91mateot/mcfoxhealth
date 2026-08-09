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
