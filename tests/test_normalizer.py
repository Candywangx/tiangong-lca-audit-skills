import json
from pathlib import Path

from tiangong_audit.normalizer import normalize_dataset

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/projected-api"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_projected_process_is_normalized():
    dataset = normalize_dataset(load("process-audit-input-approved-projected.json"))
    assert dataset["schema_version"] == "tiangong-audit-normalized-v1"
    assert dataset["dataset_type"] == "process"
    assert dataset["identity"]["name"]["zh"] == "自来水生产"
    assert dataset["coverage"]["input_count"] == 10
    assert dataset["coverage"]["output_count"] == 3
    assert dataset["reference_flow"]["pointer"] == "0"
    assert len(dataset["reference_flow"]["exchanges"]) == 1


def test_normalization_is_idempotent():
    dataset = normalize_dataset(load("process-audit-input-projected.json"))
    assert normalize_dataset(dataset) == dataset


def test_exchange_missing_metadata_is_preserved():
    dataset = normalize_dataset(load("process-audit-input-noapproved-projected.json"))
    peroxide = next(item for item in dataset["exchanges"]["inputs"] if "过氧化钠" in item["name"]["raw"])
    assert peroxide["name"]["zh"].startswith("过氧化钠")
    assert peroxide["name"]["en"].startswith("Sodium peroxide")
    assert peroxide["flow_type"] == ""
    assert peroxide["classification"] == []


def test_raw_tidas_process_extracts_exchange_and_flow_dataset_metadata():
    payload = {
        "processDataSet": {
            "processInformation": {
                "dataSetInformation": {
                    "UUID": "process-raw-1",
                    "name": {
                        "baseName": [
                            {"@xml:lang": "zh", "#text": "鲍鱼养殖"},
                            {"@xml:lang": "en", "#text": "Abalone farming"},
                        ]
                    },
                    "referenceToReferenceFlow": "0",
                }
            },
            "modellingAndValidation": {
                "LCIMethodAndAllocation": {
                    "typeOfDataSet": "Unit process, black box",
                    "dataCutOffAndCompletenessPrinciples": [
                        {"@xml:lang": "zh", "#text": "-"},
                        {"@xml:lang": "en", "#text": "-"},
                    ],
                }
            },
            "administrativeInformation": {
                "publicationAndOwnership": {
                    "dataSetVersion": "01.01.000",
                }
            },
            "exchanges": {
                "exchange": [
                    {
                        "@dataSetInternalID": "0",
                        "exchangeDirection": "Output",
                        "meanAmount": "1",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-output",
                            "@version": "02.00.000",
                            "shortDescription": [
                                {"@xml:lang": "zh", "#text": "鲍鱼；鲜活；养殖场"},
                                {"@xml:lang": "en", "#text": "Abalone; live; at farm"},
                            ],
                        },
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {"@xml:lang": "zh", "#text": "鲍鱼；鲜活；养殖场"},
                                            {"@xml:lang": "en", "#text": "Abalone; live; at farm"},
                                        ]
                                    },
                                    "classificationInformation": {
                                        "classification": {
                                            "class": [
                                                {"@level": "0", "#text": "Products"},
                                                {"@level": "1", "#text": "Aquaculture products"},
                                            ]
                                        }
                                    },
                                },
                                "quantitativeReference": {
                                    "referenceToReferenceFlowProperty": "mass-property"
                                },
                            },
                            "modellingAndValidation": {
                                "LCIMethod": {"typeOfDataSet": "Product flow"}
                            },
                            "flowProperties": {
                                "flowProperty": {
                                    "@dataSetInternalID": "mass-property",
                                    "referenceToFlowPropertyDataSet": {
                                        "shortDescription": [
                                            {"@xml:lang": "zh", "#text": "质量"},
                                            {"@xml:lang": "en", "#text": "Mass"},
                                        ]
                                    },
                                    "referenceToUnitGroupDataSet": {
                                        "shortDescription": [
                                            {"@xml:lang": "zh", "#text": "kg"},
                                            {"@xml:lang": "en", "#text": "kg"},
                                        ]
                                    },
                                }
                            },
                        },
                    },
                    {
                        "@dataSetInternalID": "1",
                        "exchangeDirection": "Input",
                        "meanAmount": "12",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-oxygen",
                            "@version": "03.00.001",
                            "shortDescription": [
                                {"@xml:lang": "en", "#text": "Purchased industrial oxygen"}
                            ],
                        },
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {"@xml:lang": "zh", "#text": "工业氧气"},
                                            {"@xml:lang": "en", "#text": "Industrial oxygen"},
                                        ]
                                    },
                                    "classificationInformation": {
                                        "classification": {
                                            "class": {"@level": "1", "#text": "Resources from air"}
                                        }
                                    },
                                },
                                "quantitativeReference": {
                                    "referenceToReferenceFlowProperty": "mass-property"
                                },
                            },
                            "modellingAndValidation": {
                                "LCIMethod": {"typeOfDataSet": "Elementary flow"}
                            },
                            "flowProperties": {
                                "flowProperty": {
                                    "@dataSetInternalID": "mass-property",
                                    "referenceToFlowPropertyDataSet": {
                                        "shortDescription": {"@xml:lang": "en", "#text": "Mass"}
                                    },
                                    "referenceToUnitGroupDataSet": {
                                        "shortDescription": {"@xml:lang": "en", "#text": "kg"}
                                    },
                                }
                            },
                        },
                    },
                    {
                        "@dataSetInternalID": "2",
                        "exchangeDirection": "Input",
                        "meanAmount": "2",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-calcium-carbonate",
                            "@version": "01.00.000",
                            "shortDescription": [
                                {"@xml:lang": "zh", "#text": "碳酸钙投入"},
                                {"@xml:lang": "en", "#text": "Calcium carbonate input"},
                            ],
                        },
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {
                                                "@xml:lang": "en",
                                                "#text": "Calcium carbonate, in ground",
                                            }
                                        ]
                                    },
                                    "classificationInformation": {
                                        "classification": {
                                            "class": {"@level": "1", "#text": "Resources from ground"}
                                        }
                                    },
                                },
                                "quantitativeReference": {
                                    "referenceToReferenceFlowProperty": "mass-property"
                                },
                            },
                            "modellingAndValidation": {
                                "LCIMethod": {"typeOfDataSet": "Elementary flow"}
                            },
                        },
                    },
                ]
            },
        }
    }

    dataset = normalize_dataset(payload)

    assert dataset["source"]["extraction_method"] == "raw-tidas"
    assert dataset["identity"]["id"] == "process-raw-1"
    assert dataset["identity"]["version"] == "01.01.000"
    assert dataset["identity"]["name"]["zh"] == "鲍鱼养殖"

    oxygen = next(item for item in dataset["exchanges"]["inputs"] if item["flow_uuid"] == "flow-oxygen")
    assert oxygen["internal_id"] == "1"
    assert oxygen["flow_version"] == "03.00.001"
    assert oxygen["flow_type"] == "Elementary flow"
    assert oxygen["classification"] == [{"level": "1", "name": "Resources from air"}]
    assert oxygen["reference_property"]["en"] == "Mass"
    assert oxygen["reference_unit"]["en"] == "kg"
    assert oxygen["unit"]["en"] == "kg"
    assert oxygen["exchange_description"]["zh"] == ""
    assert oxygen["exchange_description"]["en"] == "Purchased industrial oxygen"
    assert oxygen["flow_dataset_name"]["zh"] == "工业氧气"

    calcium_carbonate = next(
        item for item in dataset["exchanges"]["inputs"] if item["flow_uuid"] == "flow-calcium-carbonate"
    )
    assert calcium_carbonate["exchange_description"]["zh"] == "碳酸钙投入"
    assert calcium_carbonate["flow_dataset_name"]["zh"] == ""
    assert calcium_carbonate["name"]["zh"] == "碳酸钙投入"


def test_raw_tidas_process_reads_platform_prefixed_flow_classification():
    payload = {
        "processDataSet": {
            "processInformation": {"dataSetInformation": {"referenceToReferenceFlow": "0"}},
            "exchanges": {
                "exchange": {
                    "@dataSetInternalID": "0",
                    "exchangeDirection": "Output",
                    "referenceToFlowDataSet": {
                        "@refObjectId": "flow-steel",
                        "@version": "01.00.000",
                    },
                    "flowDataSet": {
                        "flowInformation": {
                            "dataSetInformation": {
                                "classificationInformation": {
                                    "common:classification": {
                                        "common:class": [
                                            {"@level": "0", "#text": "Materials"},
                                            {"@level": "1", "#text": "Steel products"},
                                        ]
                                    }
                                }
                            }
                        },
                        "modellingAndValidation": {
                            "LCIMethod": {"typeOfDataSet": "Product flow"}
                        },
                    },
                }
            },
        }
    }

    exchange = normalize_dataset(payload)["exchanges"]["outputs"][0]

    assert exchange["flow_type"] == "Product flow"
    assert exchange["classification"] == [
        {"level": "0", "name": "Materials"},
        {"level": "1", "name": "Steel products"},
    ]
    assert exchange["flow_metadata_status"] == "resolved"


def test_raw_tidas_process_accepts_list_valued_classification_container():
    for classification_key, class_key in (
        ("common:classification", "common:class"),
        ("classification", "class"),
    ):
        payload = {
            "processDataSet": {
                "processInformation": {"dataSetInformation": {}},
                "exchanges": {
                    "exchange": {
                        "exchangeDirection": "Input",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-list-classification",
                            "@version": "01.00.000",
                        },
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "classificationInformation": {
                                        classification_key: [
                                            {
                                                class_key: {
                                                    "@level": "1",
                                                    "#text": "Steel products",
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    },
                }
            },
        }

        exchange = normalize_dataset(payload)["exchanges"]["inputs"][0]

        assert exchange["classification"] == [
            {"level": "1", "name": "Steel products"}
        ]


def test_raw_tidas_process_reads_elementary_flow_categorization():
    payload = {
        "processDataSet": {
            "processInformation": {"dataSetInformation": {}},
            "exchanges": {
                "exchange": {
                    "exchangeDirection": "Output",
                    "referenceToFlowDataSet": {
                        "@refObjectId": "flow-carbon-dioxide",
                        "@version": "03.00.004",
                    },
                    "flowDataSet": {
                        "flowInformation": {
                            "dataSetInformation": {
                                "classificationInformation": {
                                    "common:elementaryFlowCategorization": {
                                        "common:category": [
                                            {"@level": "0", "#text": "Emissions"},
                                            {"@level": "1", "#text": "Emissions to air"},
                                            {
                                                "@level": "2",
                                                "#text": "Emissions to air, unspecified",
                                            },
                                        ]
                                    }
                                }
                            }
                        },
                        "modellingAndValidation": {
                            "LCIMethod": {"typeOfDataSet": "Elementary flow"}
                        },
                    },
                }
            },
        }
    }

    exchange = normalize_dataset(payload)["exchanges"]["outputs"][0]

    assert exchange["classification"] == [
        {"level": "0", "name": "Emissions"},
        {"level": "1", "name": "Emissions to air"},
        {"level": "2", "name": "Emissions to air, unspecified"},
    ]


def test_raw_tidas_reference_without_embedded_flow_is_not_fetched():
    payload = {
        "processDataSet": {
            "processInformation": {"dataSetInformation": {}},
            "exchanges": {
                "exchange": {
                    "@dataSetInternalID": "1",
                    "exchangeDirection": "Input",
                    "referenceToFlowDataSet": {
                        "@refObjectId": "flow-water",
                        "@version": "01.00.000",
                    },
                }
            },
        }
    }

    exchange = normalize_dataset(payload)["exchanges"]["inputs"][0]

    assert exchange["flow_metadata_status"] == "not_fetched"


def test_raw_tidas_process_extracts_common_fields_and_process_quantitative_reference():
    payload = {
        "processDataSet": {
            "processInformation": {
                "dataSetInformation": {
                    "UUID": "panel-process",
                    "name": {
                        "baseName": [
                            {"@xml:lang": "en", "#text": "Composite panel manufacture"},
                            {"@xml:lang": "zh", "#text": "复合板制造"},
                        ],
                        "treatmentStandardsRoutes": [
                            {
                                "@xml:lang": "en",
                                "#text": "Composite material, vacuum infusion, at plant",
                            },
                            {"@xml:lang": "zh", "#text": "复合材料，真空灌注，在工厂"},
                        ],
                    },
                    "common:generalComment": [
                        {
                            "@xml:lang": "en",
                            "#text": "This dataset excludes upstream material production impacts.",
                        },
                        {"@xml:lang": "zh", "#text": "本数据集不包含上游材料生产的环境影响。"},
                    ],
                },
                "quantitativeReference": {
                    "@type": "Reference flow(s)",
                    "referenceToReferenceFlow": "0",
                },
                "technology": {
                    "technologyDescriptionAndIncludedProcesses": [
                        {
                            "@xml:lang": "en",
                            "#text": "The dataset covers panel forming. Upstream production burdens are represented through the linked input product flow.",
                        },
                        {
                            "@xml:lang": "zh",
                            "#text": "本数据集覆盖复合板成型。上游材料生产负荷通过输入产品流链接体现。",
                        },
                    ]
                },
            },
            "modellingAndValidation": {
                "LCIMethodAndAllocation": {
                    "typeOfDataSet": "Unit process, single operation",
                },
                "dataSourcesTreatmentAndRepresentativeness": {
                    "annualSupplyOrProductionVolume": [
                        {"@xml:lang": "en", "#text": "3 Composite panels"},
                        {"@xml:lang": "zh", "#text": "3 复合板"},
                    ],
                    "dataCutOffAndCompletenessPrinciples": [
                        {
                            "@xml:lang": "en",
                            "#text": "Manufacturing energy was not separately reported in the source and is not included.",
                        },
                        {"@xml:lang": "zh", "#text": "制造能耗未在来源中单独列出，因此未纳入。"},
                    ],
                },
            },
            "exchanges": {
                "exchange": [
                    {
                        "@dataSetInternalID": "0",
                        "exchangeDirection": "Output",
                        "meanAmount": "3",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "panel-flow",
                            "@version": "01.01.000",
                            "common:shortDescription": [
                                {"@xml:lang": "en", "#text": "Composite panel; at plant"},
                                {"@xml:lang": "zh", "#text": "复合板; 在工厂"},
                            ],
                        },
                    }
                ]
            },
        }
    }

    dataset = normalize_dataset(payload)

    assert dataset["reference_flow"]["pointer"] == "0"
    assert len(dataset["reference_flow"]["exchanges"]) == 1
    assert dataset["sections"]["过程信息"]["fields"]["数据集一般性说明"]["zh"] == (
        "本数据集不包含上游材料生产的环境影响。"
    )
    assert dataset["sections"]["过程信息"]["fields"]["处理、标准、路线"]["zh"] == (
        "复合材料，真空灌注，在工厂"
    )
    assert dataset["sections"]["建模信息"]["fields"]["数据切断和完整性原则"]["zh"] == (
        "制造能耗未在来源中单独列出，因此未纳入。"
    )
    assert dataset["sections"]["建模信息"]["fields"]["年产量或参考产量"]["zh"] == "3 复合板"
    output = dataset["exchanges"]["outputs"][0]
    assert output["is_reference"] is True
    assert output["name"]["zh"] == "复合板; 在工厂"
