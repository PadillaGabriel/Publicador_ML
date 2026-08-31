from io import BytesIO

import pytest
from PIL import Image

from app.products.image_policy import ImagePolicyError, validate_image_content


def _png(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height)).save(output, format="PNG")
    return output.getvalue()


def test_image_policy_accepts_marketplace_sized_image():
    inspection = validate_image_content(_png(1200, 1200))
    assert inspection.width == 1200
    assert inspection.height == 1200
    assert inspection.format == "PNG"


def test_image_policy_rejects_image_below_minimum_side():
    with pytest.raises(ImagePolicyError):
        validate_image_content(_png(499, 1200))
