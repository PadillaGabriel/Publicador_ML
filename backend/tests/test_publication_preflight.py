from app.publication.errors import provider_validation_issues


def test_missing_conditional_attribute_uses_dynamic_category_label():
    payload = {
        "message": "Validation error",
        "error": "validation_error",
        "status": 400,
        "cause": [
            {
                "code": "item.attribute.missing_conditional_required",
                "message": (
                    "The attributes [IMPORT_DUTY] are required for category [MLA74532]. "
                    "Check the attribute is present in the attributes list or in all variation's "
                    "attributes_combination or attributes."
                ),
                "type": "error",
            }
        ],
    }
    schema = {
        "fields": [
            {
                "id": "IMPORT_DUTY",
                "label": "Arancel de importación",
                "conditional_required": True,
            }
        ]
    }

    assert provider_validation_issues(payload, schema) == [
        {
            "code": "item.attribute.missing_conditional_required",
            "field": "attributes.IMPORT_DUTY",
            "message": "Mercado Libre requiere completar Arancel de importación para esta publicación.",
            "provider_message": payload["cause"][0]["message"],
        }
    ]


def test_provider_warning_does_not_block_publication_preflight():
    payload = {
        "message": "Validation error",
        "error": "validation_error",
        "status": 400,
        "cause": [
            {
                "code": "shipping.lost_me1_by_user",
                "message": "User has not mode me1",
                "type": "warning",
            }
        ],
    }

    assert provider_validation_issues(payload, {"fields": []}) == []


def test_provider_mixed_warning_and_error_only_blocks_error():
    payload = {
        "message": "Validation error",
        "error": "validation_error",
        "status": 400,
        "cause": [
            {
                "code": "shipping.lost_me1_by_user",
                "message": "User has not mode me1",
                "type": "warning",
            },
            {
                "code": "item.attribute.missing_conditional_required",
                "message": "The attributes [IMPORT_DUTY] are required for category [MLA74532].",
                "type": "error",
            },
        ],
    }
    schema = {
        "fields": [
            {
                "id": "IMPORT_DUTY",
                "label": "Arancel de importación",
                "conditional_required": True,
            }
        ]
    }

    assert provider_validation_issues(payload, schema) == [
        {
            "code": "item.attribute.missing_conditional_required",
            "field": "attributes.IMPORT_DUTY",
            "message": "Mercado Libre requiere completar Arancel de importación para esta publicación.",
            "provider_message": payload["cause"][1]["message"],
        }
    ]
